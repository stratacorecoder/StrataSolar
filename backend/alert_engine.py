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


_KNOWN_RULE_IDS = frozenset({
    'device_unreachable',
    'grabber_stale',
    'zero_production_daylight',
    'production_below_forecast',
    'production_below_baseline',
    'production_spike',
    'consumption_spike',
    'battery_low_soc',
    'battery_stuck',
})

_SEVERITY = {
    'device_unreachable': 'critical',
    'grabber_stale': 'critical',
    'zero_production_daylight': 'warning',
    'production_below_forecast': 'warning',
    'production_below_baseline': 'warning',
    'production_spike': 'warning',
    'consumption_spike': 'warning',
    'battery_low_soc': 'warning',
    'battery_stuck': 'info',
}


def _utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def retire_obsolete_open_alerts(db):
    '''Resolve open alerts for rule_ids no longer evaluated (idempotent).'''
    rows = db.execute(
        "SELECT DISTINCT rule_id FROM alerts WHERE status='open'")
    if not rows:
        return []
    now = _utc_now_iso()
    retired = []
    for (rule_id,) in rows:
        if rule_id in _KNOWN_RULE_IDS:
            continue
        db.execute_params_no_result(
            "UPDATE alerts SET status='resolved', ended_at=? "
            "WHERE status='open' AND rule_id=?",
            (now, rule_id))
        db.execute_params_no_result(
            "DELETE FROM alert_rule_state WHERE rule_id=?",
            (rule_id,))
        retired.append(rule_id)
    return retired


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


def _forecast_lat_lon(config_data):
    block = config_data.get('forecast')
    if not isinstance(block, dict):
        return None, None
    has_coords = (
        block.get('latitude') is not None or block.get('longitude') is not None)
    try:
        from feature_settings import forecast_settings
        fcfg = forecast_settings(config_data)
        lat = fcfg.get('latitude')
        lon = fcfg.get('longitude')
        if has_coords and (lat is None or lon is None):
            logging.warning(
                "Alerts: forecast coordinates invalid; solar daylight "
                "gating for zero_production and battery_stuck is disabled")
        return lat, lon
    except Exception:
        if has_coords:
            logging.warning(
                "Alerts: forecast coordinates invalid; solar daylight "
                "gating for zero_production and battery_stuck is disabled")
        return None, None


def _in_daylight(settings, config_data, tz, now_local):
    lat, lon = _forecast_lat_lon(config_data)
    if lat is not None and lon is not None:
        from solar_time import daylight_active_at
        return daylight_active_at(
            lat, lon, now_local, settings['daylight_sun_elevation_deg'])
    if not settings['daylight_rules_enabled']:
        return False
    hour = now_local.hour
    return (
        settings['daylight_start_hour'] <= hour < settings['daylight_end_hour'])


def _suppress_device_unreachable(settings, config_data, tz, now_local):
    lat, lon = _forecast_lat_lon(config_data)
    if lat is not None and lon is not None:
        if not settings['device_unreachable_night_suppress']:
            return False
        from solar_time import suppress_device_unreachable_at
        return suppress_device_unreachable_at(
            lat, lon, now_local,
            settings['daylight_sun_elevation_deg'],
            settings['device_unreachable_sunrise_grace_minutes'])
    qs = settings['device_unreachable_quiet_start_hour']
    qe = settings['device_unreachable_quiet_end_hour']
    if qs is not None and qe is not None:
        hour = now_local.hour
        if qs <= qe:
            return qs <= hour < qe
        return hour >= qs or hour < qe
    return False


def _eval_device_unreachable(db, config, device, tz, settings, opened):
    interval_s = int(config.config_data['grabber']['interval_s'])
    stale_limit = max(
        settings['device_stale_min_s'],
        settings['device_stale_multiplier'] * interval_s)
    dev_age = device_success_age_seconds(db)
    dev_stale = dev_age is None or dev_age > stale_limit
    now_local = local_now(tz)
    open_id, _wa, _si, _lj = _get_rule_state(db, 'device_unreachable')
    if (dev_stale and open_id is None
            and _suppress_device_unreachable(
                settings, config.config_data, tz, now_local)):
        dev_stale = False
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


def _eval_grabber_stale(db, settings, interval_s, opened):
    loop_age = grabber_loop_age_seconds(db)
    stale_limit = max(
        settings['device_stale_min_s'],
        settings['device_stale_multiplier'] * interval_s)
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


def _eval_zero_production(
        db, device, settings, in_daylight, power_kw, opened):
    open_id, _wa, _si, _lj = _get_rule_state(db, 'zero_production_daylight')
    if open_id is not None:
        active = power_kw <= settings['zero_production_kw']
    else:
        active = (
            in_daylight and power_kw <= settings['zero_production_kw'])
    new_id = _transition(
        db,
        'zero_production_daylight',
        active,
        'No production during daylight',
        'PV output is near zero during expected daylight hours.',
        {'power_kw': power_kw},
        settings,
        open_after_minutes=settings['zero_production_minutes'])
    if new_id:
        opened.append(new_id)


def _eval_battery_rules(db, device, settings, in_daylight, opened):
    soc = getattr(device, 'battery_soc_percent', None)
    if soc is None:
        return
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

    near_full = soc >= 98.0
    near_min = soc <= settings['battery_low_soc_percent'] + 2.0
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
        return

    soc_unchanged = abs(soc - prev_soc) < 0.5
    open_id, _wa, _si, _lj = _get_rule_state(db, 'battery_stuck')
    if open_id is not None:
        active = soc_unchanged and not near_full and not near_min
    else:
        active = (
            soc_unchanged and in_daylight
            and not near_full and not near_min)
    new_id = _transition(
        db,
        'battery_stuck',
        active,
        'Battery level unchanged',
        'Battery SOC has not moved during daylight (check BMS/inverter).',
        {'soc_percent': soc, 'previous_soc': prev_soc},
        settings,
        open_after_minutes=settings['battery_stuck_minutes'])
    if new_id:
        opened.append(new_id)
    if not soc_unchanged:
        _set_rule_state(
            db, track_key, None, False, None, json.dumps({'soc': soc}))


def evaluate_alerts(
        config, db, device, tz, forecast_payload=None,
        include_grabber_stale=False):
    '''Run all alert rules; returns list of newly opened alert ids.'''
    retire_obsolete_open_alerts(db)
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

    _eval_device_unreachable(db, config, device, tz, settings, opened)
    if include_grabber_stale:
        _eval_grabber_stale(db, settings, interval_s, opened)

    in_daylight = _in_daylight(settings, config.config_data, tz, now_local)
    power_kw = getattr(device, 'current_power_produced_kw', 0.0) or 0.0
    _eval_zero_production(db, device, settings, in_daylight, power_kw, opened)

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
        if below_base and forecast_payload:
            forecast_today = forecast_payload.get('today_forecast_kwh')
            if (forecast_today is not None
                    and forecast_today < median * 0.55):
                below_base = False
        lat, lon = _forecast_lat_lon(config.config_data)
        streak_need = settings['baseline_consecutive_days']
        if lat is None or lon is None:
            streak_need = 1
        _bid, _bact, _bsince, blast = _get_rule_state(
            db, 'production_below_baseline_track')
        streak = 0
        last_day = None
        if blast:
            try:
                meta = json.loads(blast)
                streak = int(meta.get('streak', 0))
                last_day = meta.get('last_day')
            except ValueError:
                streak = 0
        if below_base:
            if last_day == day_string:
                pass
            elif last_day == (
                    local_today(tz) - timedelta(days=1)).isoformat():
                streak += 1
            else:
                streak = 1
            last_day = day_string
        else:
            streak = 0
            last_day = day_string
        _set_rule_state(
            db, 'production_below_baseline_track', None, below_base,
            _utc_now_iso(),
            json.dumps({'streak': streak, 'last_day': last_day}))
        below_active = below_base and streak >= streak_need
        new_id = _transition(
            db,
            'production_below_baseline',
            below_active,
            'Production below historical baseline',
            'Today\'s production is far below the recent median for this time of year.',
            {'actual_kwh': actual, 'median_kwh': median, 'streak_days': streak},
            settings)
        if new_id:
            opened.append(new_id)

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

    _eval_battery_rules(db, device, settings, in_daylight, opened)

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


def _parse_resolved_cursor(cursor):
    if not cursor:
        return None, None
    parts = cursor.split(',', 1)
    if len(parts) != 2:
        raise ValueError('invalid resolved_cursor')
    ended_at = parts[0].strip()
    try:
        alert_id = int(parts[1].strip())
    except ValueError:
        raise ValueError('invalid resolved_cursor')
    if not ended_at:
        raise ValueError('invalid resolved_cursor')
    return ended_at, alert_id


def _resolved_cursor_for_row(alert):
    ended = alert.get('ended_at') or alert.get('started_at') or ''
    return f"{ended},{alert['id']}"


def alerts_for_api(
        db, open_limit=500, resolved_limit=50, resolved_cursor=None):
    open_rows = db.execute_params(
        "SELECT id, rule_id, severity, title, message, started_at, "
        "ended_at, acknowledged_at, status, detail_json FROM alerts "
        "WHERE status='open' ORDER BY started_at DESC LIMIT ?",
        (open_limit,))
    params = []
    where_extra = ''
    if resolved_cursor:
        ended_at, alert_id = _parse_resolved_cursor(resolved_cursor)
        where_extra = (
            " AND (COALESCE(ended_at, started_at) < ? "
            "OR (COALESCE(ended_at, started_at) = ? AND id < ?))")
        params.extend([ended_at, ended_at, alert_id])
    query = (
        "SELECT id, rule_id, severity, title, message, started_at, "
        "ended_at, acknowledged_at, status, detail_json FROM alerts "
        "WHERE status='resolved'" + where_extra
        + " ORDER BY COALESCE(ended_at, started_at) DESC, id DESC "
        "LIMIT ?")
    params.append(resolved_limit + 1)
    resolved_rows = db.execute_params(query, tuple(params))
    resolved_has_more = len(resolved_rows) > resolved_limit
    if resolved_has_more:
        resolved_rows = resolved_rows[:resolved_limit]
    resolved = [_row_to_alert(r) for r in resolved_rows]
    next_cursor = None
    if resolved_has_more and resolved:
        next_cursor = _resolved_cursor_for_row(resolved[-1])
    return (
        [_row_to_alert(r) for r in open_rows],
        resolved,
        resolved_has_more,
        next_cursor,
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
