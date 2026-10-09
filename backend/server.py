import json
import sys
from datetime import date
import logging
from flask import Flask, request, send_from_directory, make_response
from flask_compress import Compress

# Project imports
from aggregates import (
    PRODUCED_DELTA_SQL,
    count_recorded_days,
    deltas_from_row,
    device_lifetime_counters,
    first_recorded_day,
    recorded_energy_totals,
    sum_days_deltas,
)
from config import Config, ConfigError
import sqlite3

from database import Database, DatabaseMissingError, open_database
from local_time import (
    config_time_zone,
    configure_process_time_zone_at_startup,
    instance_clock_fields,
    local_today,
)
from health_db import (
    check_database_readable,
    read_meta_age_seconds_readonly,
)
from alert_engine import (
    acknowledge_alert,
    alerts_for_api,
    list_alerts,
    open_alert_count,
)
from forecast_service import (
    accuracy_rows_for_api,
    forecast_for_api,
    forecast_health_state,
)
from db_migrate import ensure_feature_schema
from background_worker import start_background_worker, stop_background_worker
from server_background import start_server_background, stop_server_background
from energy_recording import derived_energy_parts
from logging_setup import configure_sensitive_loggers, setup_process_logging
from query_validation import (
    QueryValidationError,
    parse_date_prefix,
    parse_export_table,
    parse_history_date,
    parse_history_detail_date,
    parse_history_table,
    parse_query_type,
    parse_real_time_hours,
)
import version

_GRABBER_LOOP_META = 'grabber_last_loop_utc'
_DEVICE_SUCCESS_META = 'device_last_success_utc'


# Globals
config = None


def _parse_config_date(value):
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _recorded_energy_totals(db):
    return recorded_energy_totals(db)


def _day_deltas(db, day_string):
    rows = db.execute_params(
        "SELECT date, produced_a, produced_b, consumed_a, consumed_b, "
        "fed_in_a, fed_in_b FROM days WHERE date=?",
        (day_string,))
    if not rows:
        return 0.0, 0.0, 0.0
    return deltas_from_row(rows[0])


def _clock_fields():
    return instance_clock_fields(config_time_zone(config))


def _current_snapshot(db):
    rows_cur = db.execute("SELECT * FROM current WHERE date='cur'")
    if not rows_cur:
        return (0.0, 0.0, 0.0, 0.0, 0.0)
    row = rows_cur[0]
    return row[1], row[2], row[3], row[4], row[5]


# Main Flask web server application
app = Flask(__name__)
Compress(app)


# Converts the given rows to a CSV string
def rows_to_csv(rows):
    '''Converts the given rows to a CSV string.'''
    # Header
    csv = "date;production;consumption;feed_in\n"
    # Data
    for row in rows:
        produced, consumed, fed_in = deltas_from_row(row)
        csv += str(row[0])  # Date
        csv += ";"
        csv += str(produced)
        csv += ";"
        csv += str(consumed)
        csv += ";"
        csv += str(fed_in)
        csv += "\n"
    return csv


@app.route('/health')
def health():
    '''Liveness probe: read-only DB check and grabber loop freshness.'''
    ok, reason, detail = check_database_readable()
    if not ok:
        payload = {"state": "degraded", "reason": reason}
        if detail:
            payload["detail"] = detail
        return json.dumps(payload), 503

    interval_s = 15
    if config is not None:
        interval_s = int(config.config_data['grabber']['interval_s'])
    stale_limit = max(3 * interval_s, interval_s + 60)
    loop_age = read_meta_age_seconds_readonly(_GRABBER_LOOP_META)
    device_age = read_meta_age_seconds_readonly(_DEVICE_SUCCESS_META)
    payload = {"state": "ok", "grabber_last_loop_age_s": loop_age}
    if device_age is not None:
        payload["device_last_success_age_s"] = device_age
    try:
        health_db = open_database(create=False)
        try:
            payload["open_alerts"] = open_alert_count(health_db)
            tz = config_time_zone(config) if config else "UTC"
            payload["forecast_state"] = forecast_health_state(
                config, health_db, tz)
            if config is not None:
                from alert_engine import _forecast_lat_lon
                block = config.config_data.get('forecast')
                has_coords = (
                    isinstance(block, dict)
                    and (block.get('latitude') is not None
                         or block.get('longitude') is not None))
                lat, lon = _forecast_lat_lon(config.config_data)
                if has_coords and (lat is None or lon is None):
                    payload["alerts_daylight_gating"] = (
                        "disabled_invalid_location")
        finally:
            health_db.close()
    except Exception:
        payload["open_alerts"] = None
        payload["forecast_state"] = "unknown"

    if loop_age is None or loop_age > stale_limit:
        payload = {
            "state": "degraded",
            "reason": "grabber_stale",
            "grabber_last_loop_age_s": loop_age,
            "open_alerts": payload.get("open_alerts"),
            "forecast_state": payload.get("forecast_state"),
        }
        if device_age is not None:
            payload["device_last_success_age_s"] = device_age
        return json.dumps(payload), 503
    return json.dumps(payload), 200


@app.route('/')
# Serves the index.html
def get_index():
    '''Serves the index.html.'''
    return send_from_directory("../site", "index.html")


@app.route('/<path:path>')
# Serves all other static files
def get_file(path):
    '''Serves all other static files.'''
    return send_from_directory("../site", path)


def _json_error_response(status_code=400):
    return json.dumps({"state": "error"}), status_code


@app.route('/csv')
# Returns a .csv export from the database
def get_csv():
    '''Returns a .csv export from the database.'''
    try:
        _table = parse_export_table(request.args['table'])
        _date = parse_date_prefix(request.args.get('date', ""))
    except (KeyError, QueryValidationError):
        return _json_error_response(400)

    try:
        db = open_database(create=False)
    except DatabaseMissingError:
        return _json_error_response(503)
    try:
        if len(_date) > 0:
            # _table is allowlisted in parse_export_table (not parameterizable).
            rows = db.execute_params(
                f"SELECT * FROM {_table} WHERE date LIKE ?",
                (_date + "%",))
        else:
            # _table is allowlisted in parse_export_table (not parameterizable).
            rows = db.execute_params(f"SELECT * FROM {_table}")

        file_name = (
            f"StrataSolar_{_date}.csv" if len(_date) > 0
            else "StrataSolar_All.csv")

        csv = rows_to_csv(rows)
        response = make_response(csv)
        cd = f'attachment; filename="{file_name}"'
        response.headers["Content-Disposition"] = cd
        response.mimetype = "text/csv"
        return response
    except Exception:
        logging.exception("Bad CSV request")
        return _json_error_response(500)
    finally:
        db.close()


# Returns JSON response containing current data
def get_json_data_current():
    '''Returns JSON response containing current data'''
    db = open_database(create=False)
    tz = config_time_zone(config)
    produced, consumed, fed_in, history_first = _recorded_energy_totals(db)
    life_p, life_c, life_f = device_lifetime_counters(db)
    produced_cur, consumed_grid, consumed_pv, consumed_total, fed_in_cur = (
        _current_snapshot(db))

    produced, consumed, fed_in, consumed_self_alltime, consumed_grid_alltime = (
        derived_energy_parts(produced, consumed, fed_in))
    consumed_total_alltime = consumed_self_alltime + consumed_grid_alltime
    if consumed_total_alltime > 0:
        consumed_self_rel_alltime = (
            consumed_self_alltime / consumed_total_alltime) * 100.0
    else:
        consumed_self_rel_alltime = 100.0

    day_string = str(local_today(tz))
    produced_today, consumed_today, fed_in_today = _day_deltas(db, day_string)

    _pt, consumed_today, fed_in_today, consumed_self_today, consumed_grid_today = (
        derived_energy_parts(produced_today, consumed_today, fed_in_today))
    consumed_total_today = consumed_self_today + consumed_grid_today
    if consumed_total_today > 0:
        consumed_self_rel_today = (
            consumed_self_today / consumed_total_today) * 100.0
    else:
        consumed_self_rel_today = 100.0

    price = float(config.config_data['prices']['price_per_grid_kwh'])
    revenue = float(config.config_data['prices']['revenue_per_fed_in_kwh'])
    earned_total = max(0.0, fed_in * revenue)
    saved_total = max(0.0, consumed_self_alltime * (price - revenue))
    earned_today = max(0.0, fed_in_today * revenue)
    saved_today = max(0.0, consumed_self_today * (price - revenue))
    data = {
        "state": "ok",
        "currently_produced_w": produced_cur * 1000.0,
        "currently_consumed_grid_w": consumed_grid * 1000.0,
        "currently_consumed_pv_w": consumed_pv * 1000.0,
        "currently_consumed_total_w": consumed_total * 1000.0,
        "currently_fed_in_w": fed_in_cur * 1000.0,
        "all_time_produced_kwh": produced,
        "all_time_consumed_kwh": consumed,
        "all_time_fed_in_kwh": fed_in,
        "all_time_earned": (earned_total + saved_total),
        "all_time_autarky": consumed_self_rel_alltime,
        "today_produced_kwh": produced_today,
        "today_consumed_kwh": consumed_today,
        "today_fed_in_kwh": fed_in_today,
        "today_earned": (earned_today + saved_today),
        "today_autarky": consumed_self_rel_today,
        "history_first_recorded_date": history_first or "",
        "device_lifetime_produced_kwh": life_p,
        "device_lifetime_consumed_kwh": life_c,
        "device_lifetime_fed_in_kwh": life_f,
        **_clock_fields(),
    }
    return json.dumps(data)


# Returns JSON response containing available years
def get_json_data_statistics():
    '''Returns JSON response containing inverter statistics.'''
    tz = config_time_zone(config)
    start_date = _parse_config_date(config.config_data['device']['start_date'])
    num_days = (local_today(tz) - start_date).days
    db = open_database(create=False)
    # Average = sum of daily recorded deltas / number of day rows (same basis).
    total_production_kwh, _consumed, _fed_in = sum_days_deltas(db)
    history_first = first_recorded_day(db)
    recorded_days = count_recorded_days(db)
    if recorded_days > 0:
        average_production_kwhpd = total_production_kwh / recorded_days
    else:
        average_production_kwhpd = 0.0
    # Best day
    rows_best_day = db.execute(
        f"SELECT date, MAX({PRODUCED_DELTA_SQL}) AS produced_kwh FROM days")
    rows_best_month = db.execute(
        f"SELECT date, MAX({PRODUCED_DELTA_SQL}) AS produced_kwh "
        "FROM months")
    rows_best_year = db.execute(
        f"SELECT date, MAX({PRODUCED_DELTA_SQL}) AS produced_kwh FROM years")
    # Highest production
    rows_highest_prod = db.execute(
        "SELECT * FROM highscores WHERE type IS 'production'")
    # Assemble result data set
    data = {
        "state": "ok",
        "start_of_operation": str(start_date),
        "days_of_operation": num_days,
        "average_daily_production_kwh": average_production_kwhpd,
        "best_day_date": rows_best_day[0][0],
        "best_day_production_kwh": rows_best_day[0][1],
        "best_month_date": rows_best_month[0][0],
        "best_month_production_kwh": rows_best_month[0][1],
        "best_year_date": rows_best_year[0][0],
        "best_year_production_kwh": rows_best_year[0][1],
        "highest_production_w": rows_highest_prod[0][2] * 1000.0,
        "highest_production_date": rows_highest_prod[0][1],
        "history_first_recorded_date": history_first or "",
        "days_with_recorded_data": recorded_days,
    }
    return json.dumps(data)


# Returns JSON response containing available years
def get_json_data_dates():
    '''Returns JSON response containing available years.'''
    db = open_database(create=False)
    rows = db.execute("SELECT min(date) FROM years")
    data = {
        "state": "ok",
        "year_min": rows[0][0],
        "year_max": local_today(config_time_zone(config)).year,
        **_clock_fields(),
    }
    return json.dumps(data)


# Returns JSON response containing history details
def get_json_data_history_details(table, date_search_string):
    '''Returns JSON response containing history details.'''
    date_search_string = parse_history_detail_date(table, date_search_string)
    db = open_database(create=False)
    if len(date_search_string) > 0:
        # table is fixed by the caller or allowlisted in parse_history_detail_date.
        rows = db.execute_params(
            f"SELECT * FROM {table} WHERE date LIKE ?",
            (date_search_string + "%",))
    else:
        # table is fixed by the caller or allowlisted in parse_history_detail_date.
        rows = db.execute_params(f"SELECT * FROM {table}")
    # Build results
    data = []
    for row in rows:
        produced, consumed, fed_in = deltas_from_row(row)
        _p, _c, _f, self_use, grid = derived_energy_parts(
            produced, consumed, fed_in)
        data.append({
            "date": row[0],
            "produced_self": self_use,
            "produced_feed_in": _f,
            "consumed_from_pv": self_use,
            "consumed_from_grid": grid,
        })
    return json.dumps(data)


# Returns JSON response containing monthly data for a year
def get_json_data_real_time(hours):
    '''Returns JSON response containing monthly data for a year.'''
    hours = parse_real_time_hours(hours)
    num_results = hours * 60
    db = open_database(create=False)
    rows = db.execute_params(
        "SELECT * FROM real_time ORDER BY ID DESC LIMIT ?",
        (num_results,))
    return json.dumps(rows)


def _json_history_from_energy(produced, consumed, fed_in, daily_high_res_data):
    produced, consumed, fed_in, consumed_self, consumed_grid = (
        derived_energy_parts(produced, consumed, fed_in))
    consumed_total = consumed_self + consumed_grid

    if consumed_total > 0:
        consumed_self_rel = (consumed_self / consumed_total) * 100.0
        consumed_grid_rel = (consumed_grid / consumed_total) * 100.0
    else:
        consumed_self_rel = 100.0
        consumed_grid_rel = 0.0

    # Compute usage
    if produced > 0:
        usage_fed_in_rel = fed_in / produced * 100.0
        usage_self_consumed_rel = consumed_self / produced * 100.0
    else:
        usage_fed_in_rel = 0.0
        usage_self_consumed_rel = 100.0

    # Compute earnings
    price = float(config.config_data['prices']['price_per_grid_kwh'])
    revenue = float(config.config_data['prices']['revenue_per_fed_in_kwh'])
    earned = max(0.0, fed_in * revenue)
    saved = max(0.0, consumed_self * (price - revenue))

    data = {
        "state": "ok",
        "produced_kwh": produced,
        "consumed_total_kwh": consumed,
        "consumed_from_pv_kwh": consumed_self,
        "consumed_from_grid_kwh": consumed_grid,
        "consumed_from_pv_percent": consumed_self_rel,
        "consumed_from_grid_percent": consumed_grid_rel,
        "usage_fed_in_kwh": fed_in,
        "usage_self_consumed_kwh": consumed_self,
        "usage_fed_in_percent": usage_fed_in_rel,
        "usage_self_consumed_percent": usage_self_consumed_rel,
        "earned_feedin": earned,
        "earned_savings": saved,
        "earned_total": max(0.0, earned + saved),
        "autarky": consumed_self_rel,
        "high_res": daily_high_res_data
    }
    return json.dumps(data)


# Returns JSON response containing historical data
def get_json_data_history(table, search_date):
    '''Returns JSON response containing historical data.'''
    table = parse_history_table(table)
    search_date = parse_history_date(table, search_date)
    db = open_database(create=False)
    if table == "all_time":
        produced, consumed, fed_in, _history_first = recorded_energy_totals(db)
        year_rows = db.execute("SELECT COUNT(*) FROM years")[0][0]
        if year_rows == 0 and count_recorded_days(db) == 0:
            return json.dumps({"state": "nodata"})
        return _json_history_from_energy(produced, consumed, fed_in, "")

    # table is allowlisted in parse_history_table (not parameterizable).
    rows = db.execute_params(
        f"SELECT * FROM {table} WHERE date=?",
        (search_date,))
    if not rows:
        return json.dumps({"state": "nodata"})

    produced, consumed, fed_in = deltas_from_row(rows[0])

    daily_high_res_data = ""
    if table == "days":
        hr_rows = db.execute_params(
            "SELECT * FROM high_res WHERE date=?",
            (search_date,))
        if hr_rows:
            hrdata = hr_rows[0][1]
            if hrdata[-1] == ',':
                hrdata = hrdata[:-1]
            daily_high_res_data = "[" + hrdata + "]"

    return _json_history_from_energy(
        produced, consumed, fed_in, daily_high_res_data)


# .../query?type=current
# .../query?type=dates
# .../query?type=historical&table=days&date=2022-08-03
# etc.
def _run_query_handler(query_type):
    '''Dispatch a validated /query type to its handler.'''
    if query_type == "current":
        return get_json_data_current()
    if query_type == "dates":
        return get_json_data_dates()
    if query_type == "historical":
        return get_json_data_history(
            request.args['table'], request.args['date'])
    if query_type == "real_time":
        return get_json_data_real_time(request.args['h'])
    if query_type == "days_in_month":
        return get_json_data_history_details("days", request.args['date'])
    if query_type == "months_in_year":
        return get_json_data_history_details("months", request.args['date'])
    if query_type == "years_in_all_time":
        return get_json_data_history_details("years", "")
    if query_type == "statistics":
        return get_json_data_statistics()
    if query_type == "forecast":
        return get_json_data_forecast()
    if query_type == "alerts":
        return get_json_data_alerts()
    if query_type == "forecast_accuracy":
        return get_json_data_forecast_accuracy()
    raise QueryValidationError(f"unsupported query type: {query_type}")


def get_json_data_forecast():
    db = open_database(create=False)
    try:
        tz = config_time_zone(config)
        payload = forecast_for_api(config, db, tz)
        payload = dict(payload)
        payload.setdefault("state", "unavailable")
        payload["accuracy_recent"] = accuracy_rows_for_api(db, limit=14)
        return json.dumps(payload)
    finally:
        db.close()


def _empty_alerts_payload():
    return {
        "state": "ok",
        "open_count": 0,
        "open_alerts": [],
        "recent_resolved": [],
        "resolved_has_more": False,
    }


def _missing_db_alerts_payload():
    data = _empty_alerts_payload()
    data["state"] = "error"
    data["reason"] = "database_missing"
    return data


def _alerts_error_payload(reason='query_failed'):
    data = _empty_alerts_payload()
    data["state"] = "error"
    data["reason"] = reason
    return data


def _parse_alerts_query_params():
    status = request.args.get("status", "list")
    if status not in ("list", "open", "all"):
        raise QueryValidationError("invalid alerts status filter")
    resolved_limit = 50
    if request.args.get("resolved_limit"):
        try:
            resolved_limit = int(request.args["resolved_limit"])
        except ValueError:
            raise QueryValidationError("invalid resolved_limit")
        if resolved_limit < 1 or resolved_limit > 200:
            raise QueryValidationError("invalid resolved_limit")
    resolved_cursor = request.args.get("resolved_cursor") or None
    if resolved_cursor:
        from alert_engine import _parse_resolved_cursor
        try:
            _parse_resolved_cursor(resolved_cursor)
        except ValueError:
            raise QueryValidationError("invalid resolved_cursor")
    if request.args.get("resolved_offset"):
        raise QueryValidationError("resolved_offset is deprecated; use resolved_cursor")
    return status, resolved_limit, resolved_cursor


def get_json_data_alerts():
    try:
        status, resolved_limit, resolved_cursor = _parse_alerts_query_params()
    except QueryValidationError:
        raise
    try:
        db = open_database(create=False)
    except DatabaseMissingError:
        return json.dumps(_missing_db_alerts_payload())
    try:
        if status == "open":
            data = {
                "state": "ok",
                "open_count": open_alert_count(db),
                "open_alerts": list_alerts(db, "open", 500),
            }
            return json.dumps(data)
        open_alerts, recent_resolved, has_more, next_cursor = alerts_for_api(
            db, 500, resolved_limit, resolved_cursor)
        data = {
            "state": "ok",
            "open_count": open_alert_count(db),
            "open_alerts": open_alerts,
            "recent_resolved": recent_resolved,
            "resolved_has_more": has_more,
            "next_resolved_cursor": next_cursor,
        }
        return json.dumps(data)
    except sqlite3.OperationalError as exc:
        if 'no such table' in str(exc).lower():
            return json.dumps(_empty_alerts_payload())
        logging.exception("Alerts query failed")
        return json.dumps(_alerts_error_payload())
    except Exception:
        logging.exception("Alerts query failed")
        return json.dumps(_alerts_error_payload())
    finally:
        db.close()


def get_json_data_forecast_accuracy():
    db = open_database(create=False)
    try:
        return json.dumps({
            "state": "ok",
            "rows": accuracy_rows_for_api(db, limit=60),
        })
    finally:
        db.close()


@app.route("/query", methods=['GET'])
def handle_request():
    '''Answers all query requests.'''
    try:
        _type = parse_query_type(request.args['type'])
        logging.debug(f"Server: REST request of type '{_type}' received")
        return _run_query_handler(_type)

    except QueryValidationError:
        return _json_error_response(400)
    except KeyError:
        return _json_error_response(400)
    except DatabaseMissingError:
        return json.dumps({"state": "error", "reason": "database_missing"})
    except Exception:
        logging.exception("Error while handling HTTP request")
        data = {"state": "error"}
        return json.dumps(data)


@app.route("/alerts/acknowledge", methods=['POST'])
def handle_alert_acknowledge():
    if not request.is_json:
        return _json_error_response(415)
    try:
        body = request.get_json()
        if not isinstance(body, dict):
            raise ValueError("body")
        alert_id = int(body["id"])
    except (TypeError, ValueError, KeyError):
        return _json_error_response(400)
    try:
        db = open_database(create=False)
    except DatabaseMissingError:
        return _json_error_response(503)
    try:
        ensure_feature_schema(db)
        if not acknowledge_alert(db, alert_id):
            return _json_error_response(404)
        db.connection.commit()
        return json.dumps({"state": "ok"})
    except Exception:
        logging.exception("Alert acknowledge failed")
        return _json_error_response(500)
    finally:
        db.close()


@app.route("/name", methods=['GET'])
def handle_name():
    try:
        return json.dumps(config.instance_settings()['name'])
    except Exception:
        logging.exception("Error while handling HTTP request")
        data = {"state": "error"}
        return json.dumps(data)


# Main loop
def main():
    '''Main loop.'''

    global config

    setup_process_logging('data/server.log')

    logging.info(
        "Starting StrataSolar server version %s", version.get_version())

    try:
        logging.info("Server: Reading backend configuration from config.yml")
        config = Config("data/config.yml")
    except ConfigError as exc:
        logging.error("Server: %s", exc)
        sys.exit(1)

    logging.getLogger().setLevel(config.log_level)
    configure_sensitive_loggers()
    from legacy_notifications import warn_ignored_outbound_notifications
    warn_ignored_outbound_notifications(config.config_data)

    configure_process_time_zone_at_startup(config_time_zone(config))

    from os.path import exists
    if exists("data/db.sqlite"):
        boot_db = Database("data/db.sqlite")
        try:
            ensure_feature_schema(boot_db)
            boot_db.connection.commit()
        finally:
            boot_db.close()

    tz = config_time_zone(config)
    start_background_worker(config, tz)
    start_server_background(config)

    # Start the web server
    from waitress import serve
    serve(app,
          host=config.config_data['server']['ip'],
          port=config.config_data['server']['port'])

    # Exit
    stop_server_background()
    stop_background_worker()
    logging.info("Server: Exiting main loop")
    logging.info("Server: Shutting down gracefully")


# Main entry point of the application
if __name__ == "__main__":
    main()
