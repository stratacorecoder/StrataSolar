'''Cumulative counter sampling and reset compensation (write path).'''

import json
import time

from config import ConfigError

_META_KEY = 'counter_reset_state_v1'
_DEFAULT_CONFIRM_MINUTES = 15.0
_DEFAULT_CONFIRM_SAMPLES = 3
_DEFAULT_JITTER_KWH = 0.001


def counters_should_be_skipped(produced, consumed, fed_in):
    '''Return True when all cumulative counters are zero (no sample).'''
    return produced == 0 and consumed == 0 and fed_in == 0


def derived_energy_parts(produced, consumed, fed_in):
    '''Clamp primary deltas and derived self/grid consumption at zero.'''
    p = max(0.0, produced)
    c = max(0.0, consumed)
    f = max(0.0, fed_in)
    self_use = max(min(p - f, c), 0.0)
    grid = max(c - self_use, 0.0)
    return p, c, f, self_use, grid


class CounterResetSettings:
    '''Validated grabber counter-reset options.'''

    def __init__(self, grabber_config):
        grabber_config = grabber_config or {}
        try:
            minutes = float(grabber_config.get(
                'counter_reset_confirm_minutes', _DEFAULT_CONFIRM_MINUTES))
            samples = int(grabber_config.get(
                'counter_reset_confirm_samples', _DEFAULT_CONFIRM_SAMPLES))
            jitter = float(grabber_config.get(
                'counter_jitter_kwh', _DEFAULT_JITTER_KWH))
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                'grabber counter reset settings must be numbers') from exc
        if minutes <= 0:
            raise ConfigError(
                'grabber.counter_reset_confirm_minutes must be positive')
        if samples <= 0:
            raise ConfigError(
                'grabber.counter_reset_confirm_samples must be positive')
        if jitter < 0:
            raise ConfigError('grabber.counter_jitter_kwh must be >= 0')
        self.confirm_seconds = minutes * 60.0
        self.confirm_samples = samples
        self.jitter_kwh = jitter


class _Pending:
    def __init__(self, anchor_b, first_raw, since, count):
        self.anchor_b = anchor_b
        self.first_raw = first_raw
        self.since = since
        self.count = count

    def to_json(self):
        return {
            'anchor_b': self.anchor_b,
            'first_raw': self.first_raw,
            'since': self.since,
            'count': self.count,
        }

    @classmethod
    def from_json(cls, data):
        if not data:
            return None
        return cls(
            float(data['anchor_b']),
            float(data['first_raw']),
            float(data['since']),
            int(data['count']),
        )


class CounterResetCompensator:
    '''Per history table + channel reset confirmation (no plausibility cap).'''

    def __init__(self, settings, clock=None):
        self.settings = settings
        self._clock = clock or time.time
        self._pending = {}
        self._reset_applied = {}

    def _key(self, table, channel):
        return f'{table}:{channel}'

    def load_persisted(self, db):
        from aggregates import _ensure_meta_table
        _ensure_meta_table(db)
        rows = db.execute_params(
            "SELECT value FROM schema_meta WHERE key = ?", (_META_KEY,))
        if not rows:
            return
        try:
            blob = json.loads(rows[0][0])
        except (json.JSONDecodeError, TypeError):
            return
        for key, data in blob.get('pending', {}).items():
            pending = _Pending.from_json(data)
            if pending is not None:
                self._pending[key] = pending

    def save_persisted(self, db):
        from aggregates import _ensure_meta_table
        _ensure_meta_table(db)
        blob = {
            'pending': {
                key: p.to_json() for key, p in self._pending.items()
            },
        }
        db.execute_params_no_result(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
            (_META_KEY, json.dumps(blob)))

    def begin_poll(self, sample_time=None):
        now = sample_time if sample_time is not None else self._clock()
        self._sample_time = now
        self._reset_applied = {}

    def finish_poll(self):
        self._reset_applied = {}

    def _clear_pending(self, key):
        self._pending.pop(key, None)

    def _apply_reset(self, previous_a, previous_b, raw, first_raw):
        recorded = previous_b - previous_a
        window_gain = max(0.0, raw - first_raw)
        new_b = raw
        new_a = new_b - recorded - window_gain
        return new_a, new_b, True

    def apply_channel(self, table, channel, previous_a, previous_b, raw):
        key = self._key(table, channel)
        now = self._sample_time
        settings = self.settings

        if key in self._reset_applied:
            first_raw = self._reset_applied[key]
            return self._apply_reset(
                previous_a, previous_b, raw, first_raw)

        if raw == 0 and previous_b > 0:
            return previous_a, previous_b, False

        if raw >= previous_b - settings.jitter_kwh:
            if raw >= previous_b:
                self._clear_pending(key)
                return previous_a, raw, False
            return previous_a, previous_b, False

        pending = self._pending.get(key)
        if pending is None or pending.anchor_b != previous_b:
            pending = _Pending(previous_b, raw, now, 1)
            self._pending[key] = pending
        else:
            pending.count += 1
            if raw < pending.first_raw:
                pending.first_raw = raw

        if raw >= pending.anchor_b:
            self._clear_pending(key)
            return previous_a, raw, False

        confirmed = (
            pending.count >= settings.confirm_samples
            and (now - pending.since) >= settings.confirm_seconds)
        if not confirmed:
            return previous_a, previous_b, False

        self._reset_applied[key] = pending.first_raw
        self._clear_pending(key)
        return self._apply_reset(
            previous_a, previous_b, raw, pending.first_raw)

    def apply_row(self, table, row, produced, consumed, fed_in):
        pa, pb, rp = self.apply_channel(
            table, 'produced', row[1], row[2], produced)
        ca, cb, rc = self.apply_channel(
            table, 'consumed', row[3], row[4], consumed)
        fa, fb, rf = self.apply_channel(
            table, 'fed_in', row[5], row[6], fed_in)
        return pa, pb, ca, cb, fa, fb, (rp or rc or rf)
