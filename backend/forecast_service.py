'''Solar production (and optional consumption) forecasting.'''

import json
import logging
from datetime import date, datetime, timedelta, timezone

import requests

from aggregates import deltas_from_row
from feature_settings import forecast_settings
from local_time import local_today
from solar_curve import cumulative_hourly, default_daylight_hours, distribute_daily_kwh

_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"
_ARCHIVE = "https://archive-api.open-meteo.com/v1/archive"


def _irradiance_to_kwh(hourly_wm2, capacity_kw, loss_factor):
    '''Convert hourly global tilted irradiance W/m² to kWh for the system.'''
    total = 0.0
    for gti in hourly_wm2:
        if gti is None:
            continue
        try:
            val = float(gti)
        except (TypeError, ValueError):
            continue
        if val < 0:
            val = 0.0
        total += (val / 1000.0) * capacity_kw * loss_factor
    return total


def _fetch_open_meteo(url, params, timeout_s):
    try:
        resp = requests.get(url, params=params, timeout=timeout_s)
        resp.raise_for_status()
        return resp.json()
    except requests.RequestException:
        logging.exception("Forecast: Open-Meteo request failed")
        return None
    except ValueError:
        logging.exception("Forecast: Open-Meteo returned invalid JSON")
        return None


def _daily_from_weather_payload(payload, capacity_kw, loss_factor):
    if not payload or 'hourly' not in payload:
        return {}
    hourly = payload['hourly']
    times = hourly.get('time') or []
    gti = hourly.get('global_tilted_irradiance') or []
    by_day = {}
    for idx, t in enumerate(times):
        if idx >= len(gti):
            break
        day = t[:10]
        by_day.setdefault(day, []).append(gti[idx])
    out = {}
    for day, values in by_day.items():
        out[day] = _irradiance_to_kwh(values, capacity_kw, loss_factor)
    return out


def _history_weekday_averages(db, lookback_days, tz):
    today = local_today(tz)
    start = today - timedelta(days=lookback_days)
    rows = db.execute_params(
        "SELECT date, produced_a, produced_b, consumed_a, consumed_b, "
        "fed_in_a, fed_in_b FROM days WHERE date >= ? AND date < ?",
        (start.isoformat(), today.isoformat()))
    prod_by_dow = {}
    cons_by_dow = {}
    for row in rows:
        produced, consumed, _fed = deltas_from_row(row)
        try:
            d = date.fromisoformat(row[0])
        except ValueError:
            continue
        dow = d.weekday()
        prod_by_dow.setdefault(dow, []).append(produced)
        cons_by_dow.setdefault(dow, []).append(consumed)

    def avg_map(src):
        return {
            dow: (sum(vals) / len(vals) if vals else 0.0)
            for dow, vals in src.items()
        }

    return avg_map(prod_by_dow), avg_map(cons_by_dow)


def _calibration_ratio(db, settings, tz):
    lat = settings['latitude']
    lon = settings['longitude']
    if lat is None or lon is None:
        return 1.0

    today = local_today(tz)
    end = today - timedelta(days=1)
    start = end - timedelta(days=settings['history_days_calibration'])
    if start >= end:
        return 1.0

    params = {
        'latitude': lat,
        'longitude': lon,
        'start_date': start.isoformat(),
        'end_date': end.isoformat(),
        'hourly': 'global_tilted_irradiance',
        'tilt': settings['panel_tilt_deg'],
        'azimuth': settings['panel_azimuth_deg'],
        'timezone': 'auto',
    }
    payload = _fetch_open_meteo(
        _ARCHIVE, params, settings['open_meteo_timeout_s'])
    predicted = _daily_from_weather_payload(
        payload,
        settings['panel_capacity_kw'],
        settings['system_loss_factor'])

    rows = db.execute_params(
        "SELECT date, produced_a, produced_b, consumed_a, consumed_b, "
        "fed_in_a, fed_in_b FROM days WHERE date >= ? AND date <= ?",
        (start.isoformat(), end.isoformat()))

    ratios = []
    for row in rows:
        actual, _, _ = deltas_from_row(row)
        pred = predicted.get(row[0])
        if pred is None or pred < 0.3:
            continue
        if actual <= 0:
            continue
        ratios.append(actual / pred)
    if len(ratios) < 2:
        return 1.0
    ratios.sort()
    mid = len(ratios) // 2
    return max(0.5, min(2.0, ratios[mid]))


def _build_history_forecast(db, settings, tz, days_ahead):
    prod_dow, cons_dow = _history_weekday_averages(
        db, settings['history_days_fallback'], tz)
    if not prod_dow:
        return None, 'insufficient_history'

    today = local_today(tz)
    start_h, end_h = default_daylight_hours()
    days = []
    for offset in range(days_ahead):
        d = today + timedelta(days=offset)
        dow = d.weekday()
        prod = prod_dow.get(dow, 0.0)
        cons = cons_dow.get(dow, 0.0) if cons_dow else 0.0
        hourly = distribute_daily_kwh(prod, start_h, end_h)
        days.append({
            'date': d.isoformat(),
            'production_kwh': round(prod, 3),
            'consumption_kwh': round(cons, 3),
            'hourly_production_kwh': [round(x, 4) for x in hourly],
        })
    return {
        'source': 'history',
        'calibration_factor': 1.0,
        'days': days,
    }, 'ok'


def _build_weather_forecast(db, settings, tz, days_ahead):
    lat = settings['latitude']
    lon = settings['longitude']
    if lat is None or lon is None:
        return None, 'no_location'

    params = {
        'latitude': lat,
        'longitude': lon,
        'hourly': 'global_tilted_irradiance',
        'tilt': settings['panel_tilt_deg'],
        'azimuth': settings['panel_azimuth_deg'],
        'forecast_days': min(days_ahead, settings['forecast_days']),
        'timezone': 'auto',
    }
    payload = _fetch_open_meteo(
        _OPEN_METEO, params, settings['open_meteo_timeout_s'])
    if not payload:
        return None, 'weather_unavailable'

    daily_pred = _daily_from_weather_payload(
        payload,
        settings['panel_capacity_kw'],
        settings['system_loss_factor'])
    cal = _calibration_ratio(db, settings, tz)

    prod_dow, cons_dow = _history_weekday_averages(
        db, settings['history_days_fallback'], tz)

    today = local_today(tz)
    start_h, end_h = default_daylight_hours()
    days = []
    hourly_times = (payload.get('hourly') or {}).get('time') or []
    hourly_gti = (payload.get('hourly') or {}).get('global_tilted_irradiance') or []
    hourly_by_day = {}
    for idx, t in enumerate(hourly_times):
        if idx >= len(hourly_gti):
            break
        day = t[:10]
        hourly_by_day.setdefault(day, []).append(float(hourly_gti[idx] or 0))

    for offset in range(days_ahead):
        d = today + timedelta(days=offset)
        ds = d.isoformat()
        raw = daily_pred.get(ds, 0.0) * cal
        cons = cons_dow.get(d.weekday(), 0.0) if cons_dow else 0.0
        gti_hours = hourly_by_day.get(ds)
        if gti_hours:
            hourly = [
                max(0.0, (g / 1000.0) * settings['panel_capacity_kw']
                    * settings['system_loss_factor'] * cal)
                for g in gti_hours]
            while len(hourly) < 24:
                hourly.append(0.0)
            hourly = hourly[:24]
        else:
            hourly = distribute_daily_kwh(raw, start_h, end_h)
        days.append({
            'date': ds,
            'production_kwh': round(raw, 3),
            'consumption_kwh': round(cons, 3),
            'hourly_production_kwh': [round(x, 4) for x in hourly],
        })

    return {
        'source': 'open_meteo',
        'calibration_factor': round(cal, 4),
        'days': days,
    }, 'ok'


def build_forecast(config, db, tz):
    '''Build forecast payload; never raises.'''
    try:
        settings = forecast_settings(config.config_data)
    except Exception:
        logging.exception("Forecast: invalid settings")
        return {'state': 'unavailable', 'reason': 'config'}

    if not settings['enabled']:
        return {'state': 'disabled'}

    days_ahead = settings['forecast_days']
    recorded = db.execute("SELECT COUNT(*) FROM days")[0][0]
    if recorded < settings['min_history_days']:
        return {
            'state': 'insufficient_history',
            'min_history_days': settings['min_history_days'],
            'days_with_data': int(recorded),
        }

    body, reason = _build_weather_forecast(db, settings, tz, days_ahead)
    if body is None:
        body, reason = _build_history_forecast(db, settings, tz, days_ahead)
    if body is None:
        return {'state': reason or 'unavailable'}

    today_str = local_today(tz).isoformat()
    today_row = next((d for d in body['days'] if d['date'] == today_str), None)
    today_actual = None
    rows = db.execute_params(
        "SELECT produced_a, produced_b, consumed_a, consumed_b, "
        "fed_in_a, fed_in_b FROM days WHERE date=?",
        (today_str,))
    if rows:
        p, c, _ = deltas_from_row((today_str,) + tuple(rows[0]))
        today_actual = {
            'production_kwh': round(p, 3),
            'consumption_kwh': round(c, 3),
        }

    hourly_today = []
    cumulative = []
    if today_row:
        hourly_today = today_row.get('hourly_production_kwh') or []
        cumulative = cumulative_hourly(hourly_today)

    return {
        'state': 'ok',
        'source': body['source'],
        'calibration_factor': body.get('calibration_factor', 1.0),
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'today': today_str,
        'today_actual': today_actual,
        'today_forecast_kwh': (
            today_row['production_kwh'] if today_row else None),
        'hourly_today': hourly_today,
        'hourly_today_cumulative': [round(x, 3) for x in cumulative],
        'days': body['days'],
    }


def persist_forecast_cache(db, payload):
    try:
        db.execute_params_no_result(
            "INSERT OR REPLACE INTO forecast_cache "
            "(id, updated_at, source, payload) VALUES (1, ?, ?, ?)",
            (
                payload.get('generated_at', ''),
                payload.get('source', ''),
                json.dumps(payload),
            ))
    except Exception:
        logging.exception("Forecast: failed to persist cache")


def load_cached_forecast(db):
    try:
        rows = db.execute(
            "SELECT payload FROM forecast_cache WHERE id = 1")
        if not rows or not rows[0][0]:
            return None
        return json.loads(rows[0][0])
    except Exception:
        logging.exception("Forecast: failed to load cache")
        return None


def refresh_forecast_if_due(config, db, tz, last_refresh_monotonic, now_mono):
    settings = forecast_settings(config.config_data)
    if not settings['enabled']:
        return last_refresh_monotonic
    if now_mono - last_refresh_monotonic < settings['refresh_interval_s']:
        return last_refresh_monotonic
    payload = build_forecast(config, db, tz)
    if payload.get('state') in ('ok', 'insufficient_history', 'disabled'):
        persist_forecast_cache(db, payload)
    return now_mono


def record_yesterday_accuracy(config, db, tz):
    '''Store actual vs predicted for the previous local day.'''
    try:
        settings = forecast_settings(config.config_data)
        if not settings['enabled']:
            return
        yesterday = local_today(tz) - timedelta(days=1)
        y = yesterday.isoformat()
        rows = db.execute_params(
            "SELECT date FROM forecast_accuracy WHERE date=?", (y,))
        if rows:
            return
        cached = load_cached_forecast(db)
        predicted_p = None
        predicted_c = None
        if cached and cached.get('days'):
            for day in cached['days']:
                if day['date'] == y:
                    predicted_p = day.get('production_kwh')
                    predicted_c = day.get('consumption_kwh')
                    break
        day_rows = db.execute_params(
            "SELECT produced_a, produced_b, consumed_a, consumed_b, "
            "fed_in_a, fed_in_b FROM days WHERE date=?",
            (y,))
        if not day_rows:
            return
        actual_p, actual_c, _ = deltas_from_row((y,) + tuple(day_rows[0]))
        db.execute_params_no_result(
            "INSERT OR REPLACE INTO forecast_accuracy "
            "(date, predicted_production_kwh, actual_production_kwh, "
            "predicted_consumption_kwh, actual_consumption_kwh) "
            "VALUES (?, ?, ?, ?, ?)",
            (y, predicted_p, actual_p, predicted_c, actual_c))
    except Exception:
        logging.exception("Forecast: accuracy recording failed")


def forecast_for_api(config, db, tz):
    cached = load_cached_forecast(db)
    if cached:
        return cached
    payload = build_forecast(config, db, tz)
    if payload.get('state') == 'ok':
        persist_forecast_cache(db, payload)
    return payload


def accuracy_rows_for_api(db, limit=30):
    try:
        rows = db.execute_params(
            "SELECT date, predicted_production_kwh, actual_production_kwh, "
            "predicted_consumption_kwh, actual_consumption_kwh "
            "FROM forecast_accuracy ORDER BY date DESC LIMIT ?",
            (limit,))
    except Exception:
        return []
    out = []
    for row in rows:
        pred = row[1]
        actual = row[2]
        err = None
        if pred is not None and actual is not None and pred > 0.1:
            err = round((actual - pred) / pred * 100.0, 1)
        out.append({
            'date': row[0],
            'predicted_production_kwh': pred,
            'actual_production_kwh': actual,
            'production_error_percent': err,
            'predicted_consumption_kwh': row[3],
            'actual_consumption_kwh': row[4],
        })
    return out
