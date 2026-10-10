from datetime import date, timedelta
from unittest.mock import patch

import pytest

from config import Config
from database import Database
from db_migrate import ensure_feature_schema
from forecast_service import build_forecast
from solar_curve import default_daylight_hours, distribute_daily_kwh as curve_dist


def _config(tmp_path, extra=""):
    text = """
logging: normal
time_zone: Asia/Manila
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
  latitude: 14.6
  longitude: 121.0
  panel_capacity_kw: 5
  min_history_days: 3
  forecast_days: 5
""" + extra
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return Config(str(path))


def _seed_days(db, start: date, count, prod=5.0):
    for i in range(count):
        d = (start + timedelta(days=i)).isoformat()
        db.execute_params_no_result(
            "INSERT INTO days VALUES (?, 0, ?, 0, ?, 0, 0)",
            (d, prod, prod * 0.5))


def test_solar_curve_sums_to_daily():
    assert default_daylight_hours() == (6, 20)
    hourly = curve_dist(12.0, 6, 20)
    assert abs(sum(hourly) - 12.0) < 0.01
    assert hourly[3] == 0.0
    assert hourly[12] > 0


def test_insufficient_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    cfg = _config(tmp_path)
    payload = build_forecast(cfg, db, "Asia/Manila")
    assert payload["state"] == "insufficient_history"


def test_history_fallback_forecast(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    today = date.today()
    start = today - timedelta(days=14)
    _seed_days(db, start, 10, prod=8.0)
    cfg = _config(tmp_path, "forecast:\n  enabled: true\n  min_history_days: 3\n")
    with patch("forecast_service._fetch_open_meteo", return_value=None):
        with patch("forecast_service.local_today", return_value=today):
            payload = build_forecast(cfg, db, "Asia/Manila")
    assert payload["state"] == "ok"
    assert payload["source"] == "history"
    assert len(payload["days"]) >= 5


def test_weather_forecast_open_meteo_mock(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    _seed_days(db, date(2026, 9, 1), 14, prod=6.0)

    def fake_meteo(url, params, timeout_s):
        return {
            "hourly": {
                "time": ["2026-10-09T08:00", "2026-10-09T09:00"],
                "global_tilted_irradiance": [400, 500],
            }
        }

    cfg = _config(tmp_path)
    with patch("forecast_service._fetch_open_meteo", side_effect=fake_meteo):
        with patch("forecast_service.local_today", return_value=date(2026, 10, 9)):
            payload = build_forecast(cfg, db, "Asia/Manila")
    assert payload["state"] == "ok"
    assert payload["source"] == "open_meteo"
    assert payload["today_forecast_kwh"] == pytest.approx(3.825)
    # Open-Meteo radiation at 08:00 is averaged over 07:00–08:00.
    assert payload["hourly_today"][7] == pytest.approx(1.7)
    assert payload["hourly_today"][8] == pytest.approx(2.125)


def test_forecast_never_raises_on_settings_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    _seed_days(db, date(2026, 1, 1), 5)
    cfg = _config(tmp_path)

    def boom(_data):
        raise RuntimeError("simulated settings failure")

    monkeypatch.setattr("forecast_service.forecast_settings", boom)
    payload = build_forecast(cfg, db, "UTC")
    assert payload["state"] == "unavailable"


def test_weather_hour_alignment_keeps_midnight_and_missing_slots():
    from forecast_service import _daily_from_weather_payload, _hourly_gti_by_day
    times = ['2026-10-10T00:00', '2026-10-10T08:00', '2026-10-10T10:00']
    radiation = [100, 400, 500]
    hours = _hourly_gti_by_day(times, radiation)
    assert hours['2026-10-09'][23] == 100
    assert hours['2026-10-10'][7:10] == [400, 0, 500]
    daily = _daily_from_weather_payload(
        {'hourly': {'time': times, 'global_tilted_irradiance': radiation}}, 5, 0.85)
    assert daily['2026-10-09'] == pytest.approx(0.425)
    assert daily['2026-10-10'] == pytest.approx(3.825)
