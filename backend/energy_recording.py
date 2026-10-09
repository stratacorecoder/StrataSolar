'''Cumulative counter sampling: plausibility checks and confirmed resets.'''

import json
import time

_META_KEY = 'counter_runtime_v1'

# Defaults when grabber.max_power_kw is not set (residential).
_DEFAULT_MAX_POWER_KW = 50.0
_DEFAULT_CONFIRM_MINUTES = 15
_DEFAULT_CONFIRM_SAMPLES = 3
_DEFAULT_JITTER_KWH = 0.001
_POWER_HEADROOM = 1.5


def counters_should_be_skipped(produced, consumed, fed_in):
    '''Return True when all cumulative counters are zero (no sample).'''
    return produced == 0 and consumed == 0 and fed_in == 0


class CounterRecorderSettings:
    def __init__(self, grabber_config):
        grabber_config = grabber_config or {}
        self.max_power_kw = float(
            grabber_config.get('max_power_kw', _DEFAULT_MAX_POWER_KW))
        self.confirm_seconds = float(
            grabber_config.get(
                'counter_reset_confirm_minutes',
                _DEFAULT_CONFIRM_MINUTES)) * 60.0
        self.confirm_samples = int(
            grabber_config.get(
                'counter_reset_confirm_samples',
                _DEFAULT_CONFIRM_SAMPLES))
        self.jitter_kwh = float(
            grabber_config.get('counter_jitter_kwh', _DEFAULT_JITTER_KWH))


class _ChannelRuntime:
    def __init__(self):
        self.reset_anchor_b = None
        self.pending_first = None
        self.pending_since = None
        self.pending_count = 0

    def clear_pending(self):
        self.reset_anchor_b = None
        self.pending_first = None
        self.pending_since = None
        self.pending_count = 0

    def to_json(self):
        return {
            'reset_anchor_b': self.reset_anchor_b,
            'pending_first': self.pending_first,
            'pending_since': self.pending_since,
            'pending_count': self.pending_count,
        }

    @classmethod
    def from_json(cls, data):
        ch = cls()
        if not data:
            return ch
        ch.reset_anchor_b = data.get('reset_anchor_b')
        ch.pending_first = data.get('pending_first')
        ch.pending_since = data.get('pending_since')
        ch.pending_count = int(data.get('pending_count', 0))
        return ch


class GrabberCounterRecorder:
    '''Per-channel plausibility and reset confirmation (grabber process state).'''

    def __init__(self, settings, clock=None):
        self.settings = settings
        self._clock = clock or time.time
        self._last_sample_time = None
        self._channels = {
            'produced': _ChannelRuntime(),
            'consumed': _ChannelRuntime(),
            'fed_in': _ChannelRuntime(),
        }
        self._reset_confirmed_raw = {}

    def load_persisted(self, db):
        rows = db.execute_params(
            "SELECT value FROM schema_meta WHERE key = ?", (_META_KEY,))
        if not rows:
            return
        try:
            blob = json.loads(rows[0][0])
        except (json.JSONDecodeError, TypeError):
            return
        for name, ch in self._channels.items():
            self._channels[name] = _ChannelRuntime.from_json(blob.get(name))

    def save_persisted(self, db):
        from aggregates import _ensure_meta_table
        _ensure_meta_table(db)
        blob = {name: ch.to_json() for name, ch in self._channels.items()}
        db.execute_params_no_result(
            "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
            (_META_KEY, json.dumps(blob)))

    def begin_sample(self, sample_time=None, min_elapsed_s=None):
        now = sample_time if sample_time is not None else self._clock()
        if self._last_sample_time is None:
            if min_elapsed_s is not None:
                elapsed_h = max(float(min_elapsed_s) / 3600.0, 1.0 / 3600.0)
            else:
                elapsed_h = 1.0 / 3600.0
        else:
            elapsed_h = max(
                (now - self._last_sample_time) / 3600.0, 1.0 / 3600.0)
        self._last_sample_time = now
        self._sample_time = now
        self._elapsed_h = elapsed_h
        self._channels_observed = set()
        self._reset_confirmed_raw = {}

    def _max_increase_kwh(self):
        return self.settings.max_power_kw * self._elapsed_h * _POWER_HEADROOM

    def _process_one(self, previous_a, previous_b, raw, channel):
        ch = self._channels[channel]
        now = self._sample_time
        settings = self.settings
        observe_pending = channel not in self._channels_observed
        if observe_pending:
            self._channels_observed.add(channel)

        if channel in self._reset_confirmed_raw:
            if raw == self._reset_confirmed_raw[channel]:
                recorded = previous_b - previous_a
                window_gain = max(
                    0.0, raw - (ch.pending_first or raw))
                new_b = raw
                new_a = new_b - recorded - window_gain
                return new_a, new_b, True

        if raw == 0 and previous_b > 0:
            return previous_a, previous_b, False

        if raw >= previous_b - settings.jitter_kwh:
            if raw > previous_b:
                if raw - previous_b > self._max_increase_kwh():
                    return previous_a, previous_b, False
            if observe_pending:
                ch.clear_pending()
            new_b = raw if raw > previous_b else previous_b
            return previous_a, new_b, False

        anchor = previous_b
        if observe_pending:
            if ch.reset_anchor_b != anchor:
                ch.reset_anchor_b = anchor
                ch.pending_first = raw
                ch.pending_since = now
                ch.pending_count = 1
            else:
                ch.pending_count += 1
                if ch.pending_first is None:
                    ch.pending_first = raw

        if raw >= anchor:
            if observe_pending:
                ch.clear_pending()
            return previous_a, raw, False

        confirmed = (
            ch.pending_count >= settings.confirm_samples
            and ch.pending_since is not None
            and (now - ch.pending_since) >= settings.confirm_seconds)
        if not confirmed:
            return previous_a, previous_b, False

        recorded = previous_b - previous_a
        window_gain = max(0.0, raw - (ch.pending_first or raw))
        new_b = raw
        new_a = new_b - recorded - window_gain
        if observe_pending:
            self._reset_confirmed_raw[channel] = raw
        return new_a, new_b, True

    def finish_sample(self):
        '''After all history tables are updated for one device poll.'''
        for channel in self._reset_confirmed_raw:
            self._channels[channel].clear_pending()
        self._reset_confirmed_raw = {}

    def next_history_counter_columns(self, row, produced, consumed, fed_in):
        pa, pb, rp = self._process_one(row[1], row[2], produced, 'produced')
        ca, cb, rc = self._process_one(row[3], row[4], consumed, 'consumed')
        fa, fb, rf = self._process_one(row[5], row[6], fed_in, 'fed_in')
        return pa, pb, ca, cb, fa, fb, (rp or rc or rf)


def derived_energy_parts(produced, consumed, fed_in):
    '''Clamp primary deltas and derived self/grid consumption at zero.'''
    p = max(0.0, produced)
    c = max(0.0, consumed)
    f = max(0.0, fed_in)
    self_use = max(min(p - f, c), 0.0)
    grid = max(c - self_use, 0.0)
    return p, c, f, self_use, grid
