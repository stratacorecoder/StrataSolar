'''Operational anomaly detection with debounced open/resolve alerts.'''

import json
import logging
from datetime import datetime, timedelta, timezone

from aggregates import (
    device_success_age_seconds,
    grabber_loop_age_seconds,
)
from feature_settings import alerts_settings
from local_time import local_now, local_today


_SEVERITY = {
    'device_unreachable': 'critical',
    'grabber_stale': 'critical',
    'zero_production_daylight': 'warning',
    'production_below_forecast': 'warning',
    'production_below_baseline': 'warning',
    'production_spike': 'warning',
    'consumption_spike': 'warning',
    'counter_reset': 'warning',
    'negative_delta': 'warning',
    'battery_low_soc': 'warning',
    'battery_stuck': 'info',
}


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(value):
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _minutes_since(iso_ts):
    dt = _parse_iso(iso_ts)
    if dt is None:
        return 0.0
    return (datetime.now(timezone.utc) - dt).total_seconds() / 60.0


def _get_rule_state(db, rule_id):
    rows = db.execute_params(
        "SELECT open_alert_id, condition_active, condition_since, last_value_json "
        "FROM alert_rule_state WHERE rule_id=?",
        (rule_id,))
    if not rows:
        return None, 0, None, None
    return rows[0][0], int(rows[0][1]), rows[0][2], rows[0][3]


def _set_rule_state(db, rule_id, open_id, active, since, last_json):
    db.execute_params_no_result(
        "INSERT OR REPLACE INTO alert_rule_state "
        "(rule_id, open_alert_id, condition_active, condition_since, "
        "last_value_json) VALUES (?, ?, ?, ?, ?)",
        (rule_id, open_id, 1 if active else 0, since, last_json))


def _open_alert(db, rule_id, title, message, detail=None):
    sev = _SEVERITY.get(rule_id, 'warning')
    detail_json = json.dumps(detail) if detail else None
    db.execute_params_no_result(
        "INSERT INTO alerts "
        "(rule_id, severity, title, message, started_at, status, detail_json) "
        "VALUES (?, ?, ?, ?, ?, 'open', ?)",
        (rule_id, sev, title, message, _utc_now_iso(), detail_json))
    return db.execute("SELECT last_insert_rowid()")[0][0]


def _resolve_alert(db, alert_id):
    db.execute_params_no_result(
        "UPDATE alerts SET status='resolved', ended_at=? WHERE id=?",
        (_utc_now_iso(), alert_id))


def _transition(
        db, rule_id, active, title, message, detail, settings,
        open_after_minutes=1):
    open_id, was_active, since, _last = _get_rule_state(db, rule_id)
    now_iso = _utc_now_iso()

    if active and not was_active:
        since = now_iso
        _set_rule_state(db, rule_id, open_id, True, since, json.dumps(detail))
        return None

    if active and was_active:
        minutes = _minutes_since(since)
        if open_id is None and minutes >= open_after_minutes:
            new_id = _open_alert(db, rule_id, title, message, detail)
            _set_rule_state(db, rule_id, new_id, True, since, json.dumps(detail))
            return new_id
        return None

    if not active and was_active:
        clear_min = settings['resolve_clear_minutes']
        if _minutes_since(since) >= clear_min:
            if open_id is not None:
                _resolve_alert(db, open_id)
            _set_rule_state(db, rule_id, None, False, None, None)
        return None

    if not active and not was_active:
        _set_rule_state(db, rule_id, None, False, None, None)
    return None


def _day_production_so_far(db, day_string):
    rows = db.execute_params(
        "SELECT produced_a, produced_b FROM days WHERE date=?",
        (day_string,))
    if not rows:
        return 0.0
    return max(0.0, rows[0][1] - rows[0][0])


def _historical_median_production(db, tz, lookback=14):
    today = local_today(tz)
    start = (today - timedelta(days=lookback)).isoformat()
    rows = db.execute_params(
        "SELECT produced_a, produced_b FROM days WHERE date >= ? AND date < ?",
        (start, today.isoformat()))
    vals = []
    for row in rows:
        vals.append(max(0.0, row[1] - row[0]))
    if not vals:
        return None
    vals.sort()
    return vals[len(vals) // 2]


def evaluate_alerts(config, db, device, tz, forecast_payload=None):
    '''Run all alert rules; returns list of newly opened alert ids.'''
    try:
        settings = alerts_settings(config.config_data)
    except Exception:
        logging.exception("Alerts: invalid settings")
        return []

    if not settings['enabled']:
        return []

    opened = []
    interval_s = int(config.config_data['grabber']['interval_s'])
    now_local = local_now(tz)
    hour = now_local.hour
    day_string = local_today(tz).isoformat()

    # Device unreachable
    dev_age = device_success_age_seconds(db)
    stale_limit = max(
        settings['device_stale_min_s'],
        settings['device_stale_multiplier'] * interval_s)
    dev_stale = dev_age is None or dev_age > stale_limit
    new_id = _transition(
        db,
        'device_unreachable',
        dev_stale,
        'Device unreachable',
        'No successful device read within the expected interval.',
        {'device_age_s': dev_age, 'limit_s': stale_limit},
        settings)
    if new_id:
        opened.append(new_id)

    loop_age = grabber_loop_age_seconds(db)
    loop_stale = loop_age is None or loop_age > stale_limit
    new_id = _transition(
        db,
        'grabber_stale',
        loop_stale,
        'Data recording stalled',
        'The grabber loop heartbeat is older than expected.',
        {'loop_age_s': loop_age, 'limit_s': stale_limit},
        settings)
    if new_id:
        opened.append(new_id)

    in_daylight = (
        settings['daylight_start_hour'] <= hour < settings['daylight_end_hour'])
    power_kw = getattr(device, 'current_power_produced_kw', 0.0) or 0.0
    zero_daylight = (
        in_daylight and power_kw <= settings['zero_production_kw'])
    new_id = _transition(
        db,
        'zero_production_daylight',
        zero_daylight,
        'No production during daylight',
        'PV output is near zero during expected daylight hours.',
        {'power_kw': power_kw, 'hour': hour},
        settings,
        open_after_minutes=settings['zero_production_minutes'])
    if new_id:
        opened.append(new_id)

    if forecast_payload and forecast_payload.get('state') == 'ok':
        forecast_today = forecast_payload.get('today_forecast_kwh')
        if (forecast_today and forecast_today >= settings['below_forecast_min_kwh']
                and hour >= settings['below_forecast_after_hour']):
            actual = _day_production_so_far(db, day_string)
            expected = forecast_today * (hour / 24.0)
            below = (
                expected > settings['below_forecast_min_kwh']
                and actual < expected * settings['below_forecast_fraction'])
            new_id = _transition(
                db,
                'production_below_forecast',
                below,
                'Production below forecast',
                'Today\'s production is significantly below the forecast curve.',
                {
                    'actual_kwh': actual,
                    'expected_so_far_kwh': round(expected, 2),
                    'forecast_day_kwh': forecast_today,
                },
                settings)
            if new_id:
                opened.append(new_id)

    median = _historical_median_production(
        db, tz, settings['baseline_min_history_days'] + 7)
    if median and hour >= settings['below_forecast_after_hour']:
        actual = _day_production_so_far(db, day_string)
        below_base = actual < median * settings['baseline_below_fraction']
        new_id = _transition(
            db,
            'production_below_baseline',
            below_base,
            'Production below historical baseline',
            'Today\'s production is far below the recent median for this time of year.',
            {'actual_kwh': actual, 'median_kwh': median},
            settings)
        if new_id:
            opened.append(new_id)

    # Counter anomalies from last grabber sample stored in rule state
    counters = {
        'produced': getattr(device, 'total_energy_produced_kwh', None),
        'consumed': getattr(device, 'total_energy_consumed_kwh', None),
        'fed_in': getattr(device, 'total_energy_fed_in_kwh', None),
    }
    _open_id, _act, _since, last_json = _get_rule_state(db, 'counter_tracking')
    prev = {}
    if last_json:
        try:
            prev = json.loads(last_json)
        except ValueError:
            prev = {}
    drop_kwh = settings['counter_reset_drop_kwh']
    reset_detected = False
    negative_delta = False
    for key in ('produced', 'consumed', 'fed_in'):
        cur = counters.get(key)
        old = prev.get(key)
        if cur is None or old is None:
            continue
        delta = cur - old
        if delta < -0.01:
            negative_delta = True
        if old - cur >= drop_kwh:
            reset_detected = True

    if reset_detected:
        open_id, _wa, _si, _lj = _get_rule_state(db, 'counter_reset')
        if open_id is None:
            new_id = _open_alert(
                db,
                'counter_reset',
                'Inverter counter reset detected',
                'A cumulative energy counter dropped sharply (replacement or reset).',
                {'counters': counters, 'previous': prev})
            _set_rule_state(
                db, 'counter_reset', new_id, True, _utc_now_iso(),
                json.dumps({'counters': counters, 'previous': prev}))
            opened.append(new_id)
    else:
        new_id = _transition(
            db,
            'counter_reset',
            False,
            'Inverter counter reset detected',
            'A cumulative energy counter dropped sharply (replacement or reset).',
            {'counters': counters, 'previous': prev},
            settings)
        if new_id:
            opened.append(new_id)

    new_id = _transition(
        db,
        'negative_delta',
        negative_delta and not reset_detected,
        'Implausible counter decrease',
        'Energy counters decreased between polls (not a full reset).',
        {'counters': counters, 'previous': prev},
        settings)
    if new_id:
        opened.append(new_id)

    db.execute_params_no_result(
        "INSERT OR REPLACE INTO alert_rule_state "
        "(rule_id, open_alert_id, condition_active, condition_since, "
        "last_value_json) VALUES ('counter_tracking', NULL, 0, NULL, ?)",
        (json.dumps(counters),))

    # Spike detection on today's delta vs median daily
    if median and median > 0.5:
        actual = _day_production_so_far(db, day_string)
        spike = actual > max(
            settings['spike_min_delta_kwh'],
            median * settings['spike_multiplier'])
        new_id = _transition(
            db,
            'production_spike',
            spike and hour < 20,
            'Unusual production spike',
            'Today\'s production jumped far above typical daily levels.',
            {'actual_kwh': actual, 'median_kwh': median},
            settings)
        if new_id:
            opened.append(new_id)

    rows = db.execute_params(
        "SELECT consumed_a, consumed_b FROM days WHERE date=?",
        (day_string,))
    if rows and median:
        consumed_today = max(0.0, rows[0][1] - rows[0][0])
        cons_median_rows = db.execute_params(
            "SELECT consumed_a, consumed_b FROM days WHERE date < ? "
            "ORDER BY date DESC LIMIT 14",
            (day_string,))
        cons_vals = [
            max(0.0, r[1] - r[0]) for r in cons_median_rows]
        if cons_vals:
            cons_vals.sort()
            cons_med = cons_vals[len(cons_vals) // 2]
            if cons_med > 0.5:
                cons_spike = consumed_today > max(
                    settings['consumption_spike_min_kwh'],
                    cons_med * settings['consumption_spike_multiplier'])
                new_id = _transition(
                    db,
                    'consumption_spike',
                    cons_spike,
                    'Unusual consumption spike',
                    'Grid/house consumption today is far above recent levels.',
                    {
                        'consumption_kwh': consumed_today,
                        'median_kwh': cons_med,
                    },
                    settings)
                if new_id:
                    opened.append(new_id)

    soc = getattr(device, 'battery_soc_percent', None)
    if soc is not None:
        low = soc <= settings['battery_low_soc_percent']
        new_id = _transition(
            db,
            'battery_low_soc',
            low,
            'Battery state of charge low',
            f'Battery SOC is {soc:.0f}% (threshold '
            f'{settings["battery_low_soc_percent"]:.0f}%).',
            {'soc_percent': soc},
            settings)
        if new_id:
            opened.append(new_id)

        stuck_key = 'battery_stuck'
        _oid, was_active, since, last = _get_rule_state(db, stuck_key)
        prev_soc = None
        if last:
            try:
                prev_soc = json.loads(last).get('soc')
            except ValueError:
                prev_soc = None
        unchanged = (
            prev_soc is not None
            and abs(soc - prev_soc) < 0.5
            and in_daylight)
        if not unchanged:
            _set_rule_state(
                db, stuck_key, _oid, False, None, json.dumps({'soc': soc}))
        new_id = _transition(
            db,
            'battery_stuck',
            unchanged,
            'Battery level unchanged',
            'Battery SOC has not moved during daylight (check BMS/inverter).',
            {'soc_percent': soc, 'previous_soc': prev_soc},
            settings,
            open_after_minutes=settings['battery_stuck_minutes'])
        if new_id:
            opened.append(new_id)
        elif unchanged and was_active:
            _set_rule_state(
                db, stuck_key, _oid, True, since, json.dumps({'soc': soc}))
        elif not unchanged:
            _set_rule_state(
                db, stuck_key, None, False, None, json.dumps({'soc': soc}))

    return opened


def list_alerts(db, status_filter=None, limit=100):
    if status_filter == 'open':
        rows = db.execute_params(
            "SELECT id, rule_id, severity, title, message, started_at, "
            "ended_at, acknowledged_at, status, detail_json FROM alerts "
            "WHERE status='open' ORDER BY started_at DESC LIMIT ?",
            (limit,))
    else:
        rows = db.execute_params(
            "SELECT id, rule_id, severity, title, message, started_at, "
            "ended_at, acknowledged_at, status, detail_json FROM alerts "
            "ORDER BY started_at DESC LIMIT ?",
            (limit,))
    out = []
    for row in rows:
        out.append({
            'id': row[0],
            'rule_id': row[1],
            'severity': row[2],
            'title': row[3],
            'message': row[4],
            'started_at': row[5],
            'ended_at': row[6],
            'acknowledged_at': row[7],
            'status': row[8],
            'detail': json.loads(row[9]) if row[9] else None,
        })
    return out


def acknowledge_alert(db, alert_id):
    rows = db.execute_params(
        "SELECT id FROM alerts WHERE id=? AND status='open'",
        (alert_id,))
    if not rows:
        return False
    db.execute_params_no_result(
        "UPDATE alerts SET acknowledged_at=? WHERE id=?",
        (_utc_now_iso(), alert_id))
    return True


def open_alert_count(db):
    try:
        return int(db.execute(
            "SELECT COUNT(*) FROM alerts WHERE status='open'")[0][0])
    except Exception:
        return 0
