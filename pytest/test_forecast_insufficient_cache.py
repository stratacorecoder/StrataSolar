'''Cached insufficient_history must not be reported as day_rollover stale.'''

from datetime import date, datetime, timedelta, timezone

from config import Config
from database import Database
from db_migrate import ensure_feature_schema
from forecast_service import forecast_for_api, persist_forecast_cache


def _cfg(tmp_path):
    text = """
logging: normal
time_zone: UTC
device:
  type: Dummy
  start_date: 2020-01-01
prices:
  price_per_grid_kwh: 0.1
  revenue_per_fed_in_kwh: 0.1
server:
  ip: 0.0.0.0
  port: 5000
grabber:
  interval_s: 5
forecast:
  enabled: true
  latitude: 52.0
  longitude: 13.0
  min_history_days: 3
"""
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return Config(str(path))


def test_cached_insufficient_history_not_day_rollover(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    d = date.today().isoformat()
    db.execute_params_no_result(
        "INSERT INTO days VALUES (?, 0, 1, 0, 1, 0, 0)", (d,))
    persist_forecast_cache(db, {
        "state": "insufficient_history",
        "min_history_days": 3,
        "days_with_data": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    })
    cfg = _cfg(tmp_path)
    payload = forecast_for_api(cfg, db, "UTC")
    assert payload["state"] == "insufficient_history"
    assert payload.get("reason") != "day_rollover"
    db.close()
