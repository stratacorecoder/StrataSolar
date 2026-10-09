from datetime import datetime, timedelta, timezone
import pytest

from aggregates import touch_device_success_heartbeat, touch_grabber_loop_heartbeat
from alert_engine import (
    acknowledge_alert,
    evaluate_alerts,
    list_alerts,
    open_alert_count,
)
from config import Config
from database import Database
from db_migrate import ensure_feature_schema


def _minimal_config(tmp_path, alerts_extra=""):
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
  interval_s: 10
alerts:
  enabled: true
  zero_production_minutes: 15
  resolve_clear_minutes: 5
  device_stale_min_s: 30
""" + alerts_extra
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return Config(str(path))


def _boot_db(tmp_path):
    (tmp_path / "data").mkdir(exist_ok=True)
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    db.execute(
        "CREATE TABLE current (date TEXT PRIMARY KEY, produced REAL, consumed_grid REAL, "
        "consumed_pv REAL, consumed_total REAL, fed_in REAL)")
    db.execute("INSERT INTO current VALUES ('cur', 0,0,0,0,0)")
    ensure_feature_schema(db)
    touch_grabber_loop_heartbeat(db)
    touch_device_success_heartbeat(db)
    return db


class _FakeDevice:
    def __init__(self, **kwargs):
        self.current_power_produced_kw = kwargs.get("power", 3.0)
        self.total_energy_produced_kwh = kwargs.get("prod", 100.0)
        self.total_energy_consumed_kwh = kwargs.get("cons", 80.0)
        self.total_energy_fed_in_kwh = kwargs.get("fed", 40.0)
        self.battery_soc_percent = kwargs.get("soc", None)


@pytest.fixture(autouse=True)
def fast_alert_debounce(monkeypatch):
    monkeypatch.setattr("alert_engine._minutes_since", lambda _iso: 999.0)


def test_device_unreachable_opens_and_resolves(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = _boot_db(tmp_path)
    cfg = _minimal_config(tmp_path)
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    db.execute_params_no_result(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        ("device_last_success_utc", old.isoformat()))

    dev = _FakeDevice(power=0)
    evaluate_alerts(cfg, db, dev, "UTC", None)
    evaluate_alerts(cfg, db, dev, "UTC", None)
    assert open_alert_count(db) >= 1

    touch_device_success_heartbeat(db)
    dev = _FakeDevice(power=2.0)
    evaluate_alerts(cfg, db, dev, "UTC", None)
    evaluate_alerts(cfg, db, dev, "UTC", None)
    assert open_alert_count(db) == 0


def test_zero_production_daylight(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = _boot_db(tmp_path)
    cfg = _minimal_config(
        tmp_path,
        "  daylight_rules_enabled: true\n"
        "  daylight_start_hour: 4\n  daylight_end_hour: 22\n")
    fixed_now = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("alert_engine.local_now", lambda _tz: fixed_now)
    dev = _FakeDevice(power=0.0)
    evaluate_alerts(cfg, db, dev, "UTC", None)
    evaluate_alerts(cfg, db, dev, "UTC", None)
    alerts = list_alerts(db, "open")
    assert any(a["rule_id"] == "zero_production_daylight" for a in alerts)


def test_battery_low_only_when_soc_present(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = _boot_db(tmp_path)
    cfg = _minimal_config(tmp_path, "  battery_low_soc_percent: 20\n")
    dev = _FakeDevice(soc=5.0)
    evaluate_alerts(cfg, db, dev, "UTC", None)
    evaluate_alerts(cfg, db, dev, "UTC", None)
    assert any(
        a["rule_id"] == "battery_low_soc" for a in list_alerts(db, "open"))

    dev_no = _FakeDevice(soc=None)
    evaluate_alerts(cfg, db, dev_no, "UTC", None)


def test_acknowledge_alert(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = _boot_db(tmp_path)
    cfg = _minimal_config(tmp_path)
    db.execute_params_no_result(
        "INSERT INTO alerts (rule_id, severity, title, message, started_at, status) "
        "VALUES ('test', 'info', 'T', 'M', ?, 'open')",
        (datetime.now(timezone.utc).isoformat(),))
    aid = db.execute("SELECT last_insert_rowid()")[0][0]
    assert acknowledge_alert(db, aid)
    row = db.execute_params("SELECT acknowledged_at FROM alerts WHERE id=?", (aid,))[0]
    assert row[0] is not None


def test_production_below_forecast(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = _boot_db(tmp_path)
    today = datetime.now(timezone.utc).date().isoformat()
    db.execute_params_no_result(
        "INSERT INTO days VALUES (?, 0, 0.5, 0, 0, 0, 0)", (today,))
    cfg = _minimal_config(
        tmp_path,
        "  below_forecast_after_hour: 10\n  below_forecast_fraction: 0.9\n")
    forecast = {
        "state": "ok",
        "today": today,
        "today_forecast_kwh": 20.0,
    }
    dev = _FakeDevice(power=0.01)
    fixed_now = datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("alert_engine.local_now", lambda _tz: fixed_now)
    evaluate_alerts(cfg, db, dev, "UTC", forecast)
    evaluate_alerts(cfg, db, dev, "UTC", forecast)
    assert any(
        a["rule_id"] == "production_below_forecast"
        for a in list_alerts(db, "open"))
