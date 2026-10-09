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
        open_after_minutes=1, auto_resolve=True):
    open_id, was_active, since, last_json = _get_rule_state(db, rule_id)
    now_iso = _utc_now_iso()
    detail_json = json.dumps(detail) if detail is not None else last_json

    if active and not was_active:
        since = now_iso
        _set_rule_state(db, rule_id, open_id, True, since, detail_json)
        return None

    if active and was_active:
        minutes = _minutes_since(since)
        if open_id is None and minutes >= open_after_minutes:
            new_id = _open_alert(db, rule_id, title, message, detail)
            _set_rule_state(db, rule_id, new_id, True, since, detail_json)
            return new_id
        if open_id is not None and detail_json:
            _set_rule_state(db, rule_id, open_id, True, since, detail_json)
        return None

    if not active and was_active:
        _set_rule_state(db, rule_id, open_id, False, now_iso, detail_json)
        return None

    if not active and not was_active and open_id is not None:
        clear_min = settings['resolve_clear_minutes']
        if auto_resolve and since and _minutes_since(since) >= clear_min:
            _resolve_alert(db, open_id)
            _set_rule_state(db, rule_id, None, False, None, None)
        return None

    if not active and not was_active and open_id is None:
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


def _forecast_for_alerts(forecast_payload, tz):
    if not forecast_payload or forecast_payload.get('state') != 'ok':
        return None
    if forecast_payload.get('today') != local_today(tz).isoformat():
        return None
    return forecast_payload


def _in_daylight(settings, config_data, tz, now_local):
    if not settings['daylight_rules_enabled']:
        return False
    try:
        from feature_settings import forecast_settings
        fcfg = forecast_settings(config_data)
        lat, lon = fcfg.get('latitude'), fcfg.get('longitude')
    except Exception:
        lat, lon = None, None
    if lat is not None and lon is not None:
        from solar_time import solar_elevation_deg
        elev = solar_elevation_deg(lat, lon, now_local)
        return elev >= settings['daylight_sun_elevation_deg']
    hour = now_local.hour
    return (
        settings['daylight_start_hour'] <= hour < settings['daylight_end_hour'])


def evaluate_alerts(
        config, db, device, tz, forecast_payload=None,
        include_grabber_stale=False):
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

    if include_grabber_stale:
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

    in_daylight = _in_daylight(settings, config.config_data, tz, now_local)
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

    forecast_payload = _forecast_for_alerts(forecast_payload, tz)
    if forecast_payload:
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

    _pid, was_pending, _since_p, pending_json = _get_rule_state(
        db, 'counter_reset_pending')
    still_reset = False
    if was_pending and pending_json:
        try:
            stored = json.loads(pending_json)
            stored_prev = stored.get('previous') or {}
        except ValueError:
            stored_prev = {}
        for key in ('produced', 'consumed', 'fed_in'):
            old = stored_prev.get(key)
            cur = counters.get(key)
            if old is None or cur is None:
                continue
            if old - cur >= drop_kwh:
                still_reset = True
                break

    if reset_detected or still_reset:
        if not was_pending:
            _set_rule_state(
                db, 'counter_reset_pending', None, True, _utc_now_iso(),
                json.dumps({'counters': counters, 'previous': prev}))
        else:
            open_id, _wa, _si, _lj = _get_rule_state(db, 'counter_reset')
            if open_id is None:
                detail = {'counters': counters, 'previous': prev}
                if pending_json:
                    try:
                        detail = json.loads(pending_json)
                    except ValueError:
                        pass
                new_id = _open_alert(
                    db,
                    'counter_reset',
                    'Inverter counter reset detected',
                    'A cumulative energy counter dropped sharply (replacement or reset).',
                    detail)
                _set_rule_state(
                    db, 'counter_reset', new_id, True, _utc_now_iso(),
                    json.dumps(detail))
                _set_rule_state(
                    db, 'counter_reset_pending', None, False, None, None)
                opened.append(new_id)
    else:
        _set_rule_state(db, 'counter_reset_pending', None, False, None, None)
        new_id = _transition(
            db,
            'counter_reset',
            False,
            'Inverter counter reset detected',
            'A cumulative energy counter dropped sharply (replacement or reset).',
            {'counters': counters, 'previous': prev},
            settings,
            auto_resolve=False)
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

        track_key = 'battery_stuck_soc'
        _toid, _tact, _tsince, last = _get_rule_state(db, track_key)
        prev_soc = None
        if last:
            try:
                prev_soc = json.loads(last).get('soc')
            except ValueError:
                prev_soc = None
        if prev_soc is None:
            _set_rule_state(
                db, track_key, None, False, None, json.dumps({'soc': soc}))
        else:
            unchanged = (
                abs(soc - prev_soc) < 0.5
                and in_daylight)
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
            if not unchanged:
                _set_rule_state(
                    db, track_key, None, False, None, json.dumps({'soc': soc}))

    return opened


def _row_to_alert(row):
    return {
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
    }


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
    return [_row_to_alert(row) for row in rows]


def alerts_for_api(db, open_limit=500, resolved_limit=50, resolved_offset=0):
    open_rows = db.execute_params(
        "SELECT id, rule_id, severity, title, message, started_at, "
        "ended_at, acknowledged_at, status, detail_json FROM alerts "
        "WHERE status='open' ORDER BY started_at DESC LIMIT ?",
        (open_limit,))
    resolved_rows = db.execute_params(
        "SELECT id, rule_id, severity, title, message, started_at, "
        "ended_at, acknowledged_at, status, detail_json FROM alerts "
        "WHERE status='resolved' ORDER BY COALESCE(ended_at, started_at) "
        "DESC LIMIT ? OFFSET ?",
        (resolved_limit, resolved_offset))
    more = db.execute_params(
        "SELECT COUNT(*) FROM alerts WHERE status='resolved'")[0][0]
    resolved_has_more = (resolved_offset + resolved_limit) < int(more)
    return (
        [_row_to_alert(r) for r in open_rows],
        [_row_to_alert(r) for r in resolved_rows],
        resolved_has_more,
    )


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
