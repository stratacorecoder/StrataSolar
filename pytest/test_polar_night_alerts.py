'''Polar-night alert integration (evaluate_alerts).'''

from datetime import datetime, timedelta, timezone

from aggregates import touch_device_success_heartbeat
from alert_engine import evaluate_alerts, list_alerts
from config import Config
from database import Database
from db_migrate import ensure_feature_schema


class _FakeDevice:
    def __init__(self, power=0.0):
        self.current_power_produced_kw = power
        self.total_energy_produced_kwh = 100.0
        self.total_energy_consumed_kwh = 80.0
        self.total_energy_fed_in_kwh = 40.0
        self.battery_soc_percent = 55.0


def _cfg(tmp_path, lat, lon):
    text = f"""
logging: normal
time_zone: Europe/Oslo
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
  interval_s: 60
forecast:
  latitude: {lat}
  longitude: {lon}
alerts:
  enabled: true
  device_stale_min_s: 30
  zero_production_minutes: 15
  battery_stuck_minutes: 30
"""
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return Config(str(path))


def _boot(tmp_path):
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    return db


def test_tromso_polar_night_no_zero_production_or_battery_stuck(
        tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = _boot(tmp_path)
    cfg = _cfg(tmp_path, 69.65, 18.96)
    when = datetime(2024, 12, 20, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("alert_engine.local_now", lambda _tz: when)
    monkeypatch.setattr("alert_engine._minutes_since", lambda _iso: 999.0)
    dev = _FakeDevice(power=0.0)
    for _ in range(3):
        evaluate_alerts(cfg, db, dev, "Europe/Oslo", None)
    open_rules = {a["rule_id"] for a in list_alerts(db, "open")}
    assert "zero_production_daylight" not in open_rules
    assert "battery_stuck" not in open_rules
    db.close()


def test_tromso_polar_night_offline_alerts_near_noon(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = _boot(tmp_path)
    cfg = _cfg(tmp_path, 69.65, 18.96)
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    db.execute_params_no_result(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        ("device_last_success_utc", old.isoformat()))
    when = datetime(2024, 12, 20, 10, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("alert_engine.local_now", lambda _tz: when)
    monkeypatch.setattr("alert_engine._minutes_since", lambda _iso: 999.0)
    dev = _FakeDevice(power=0.0)
    evaluate_alerts(cfg, db, dev, "Europe/Oslo", None)
    evaluate_alerts(cfg, db, dev, "Europe/Oslo", None)
    assert any(
        a["rule_id"] == "device_unreachable"
        for a in list_alerts(db, "open"))
    db.close()


def test_tromso_polar_night_sleeping_inverter_not_alerted_at_1550(
        tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = _boot(tmp_path)
    cfg = _cfg(tmp_path, 69.65, 18.96)
    touch_device_success_heartbeat(db)
    when = datetime(2024, 12, 20, 15, 50, tzinfo=timezone.utc)
    monkeypatch.setattr("alert_engine.local_now", lambda _tz: when)
    monkeypatch.setattr("alert_engine._minutes_since", lambda _iso: 0.0)
    dev = _FakeDevice(power=0.0)
    evaluate_alerts(cfg, db, dev, "Europe/Oslo", None)
    evaluate_alerts(cfg, db, dev, "Europe/Oslo", None)
    assert not any(
        a["rule_id"] == "device_unreachable"
        for a in list_alerts(db, "open"))
    db.close()
