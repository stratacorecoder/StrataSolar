'''Regression tests for PR #11 QA blockers.'''

import json
import sqlite3
import threading
import time
from datetime import date, datetime, timedelta, timezone
from unittest.mock import patch

import grabber as grb
from aggregates import touch_grabber_loop_heartbeat
from alert_engine import evaluate_alerts, list_alerts, open_alert_count
from azimuth import compass_azimuth_to_open_meteo
from config import Config
from database import Database
from db_migrate import ensure_feature_schema
from forecast_service import persist_forecast_cache, run_forecast_refresh_background
from notifications import _redact_error_text


def _base_config(tmp_path, extra=""):
    text = f"""
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
{extra}
"""
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return Config(str(path))


class _FakeDevice:
    def __init__(self, **kwargs):
        self.current_power_produced_kw = kwargs.get("power", 0.0)
        self.total_energy_produced_kwh = kwargs.get("prod", 0.0)
        self.total_energy_consumed_kwh = kwargs.get("cons", 0.0)
        self.total_energy_fed_in_kwh = kwargs.get("fed", 0.0)
        self.battery_soc_percent = kwargs.get("soc", None)


def test_azimuth_compass_to_open_meteo():
    assert compass_azimuth_to_open_meteo(180) == 0.0
    assert compass_azimuth_to_open_meteo(90) == -90.0
    assert compass_azimuth_to_open_meteo(270) == 90.0


def test_webhook_error_redaction():
    url = "http://hook.example/hook?token=SECRET123"
    msg = f"500 Server Error for url: {url}"
    red = _redact_error_text(msg, url)
    assert "SECRET123" not in red
    assert "hook.example" in red or "redacted" in red.lower()


def test_resolve_hysteresis_requires_healthy_period(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    db.execute(
        "CREATE TABLE current (date TEXT PRIMARY KEY, produced REAL, consumed_grid REAL, "
        "consumed_pv REAL, consumed_total REAL, fed_in REAL)")
    db.execute("INSERT INTO current VALUES ('cur', 0,0,0,0,0)")
    ensure_feature_schema(db)
    cfg = _base_config(
        tmp_path,
        """
alerts:
  enabled: true
  device_stale_min_s: 30
  resolve_clear_minutes: 20
""")
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    db.execute_params_no_result(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        ("device_last_success_utc", old.isoformat()))

    minutes = {"value": 0.0}

    def minutes_since(iso):
        return minutes["value"]

    monkeypatch.setattr("alert_engine._minutes_since", minutes_since)
    dev = _FakeDevice(power=0)
    evaluate_alerts(cfg, db, dev, "UTC", None)
    minutes["value"] = 5.0
    evaluate_alerts(cfg, db, dev, "UTC", None)
    assert open_alert_count(db) == 1

    from aggregates import touch_device_success_heartbeat
    touch_device_success_heartbeat(db)
    dev_ok = _FakeDevice(power=2.0)
    minutes["value"] = 0.0
    evaluate_alerts(cfg, db, dev_ok, "UTC", None)
    assert open_alert_count(db) == 1
    minutes["value"] = 10.0
    evaluate_alerts(cfg, db, dev_ok, "UTC", None)
    assert open_alert_count(db) == 1
    minutes["value"] = 25.0
    evaluate_alerts(cfg, db, dev_ok, "UTC", None)
    assert open_alert_count(db) == 0
    db.close()


def test_battery_stuck_end_to_end(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    cfg = _base_config(
        tmp_path,
        """
forecast:
  latitude: 52.0
  longitude: 13.0
alerts:
  enabled: true
  daylight_rules_enabled: true
  battery_stuck_minutes: 30
""")
    noon = datetime(2026, 6, 15, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("alert_engine.local_now", lambda _tz: noon)
    monkeypatch.setattr("alert_engine._minutes_since", lambda _iso: 999.0)
    dev = _FakeDevice(soc=50.0)
    evaluate_alerts(cfg, db, dev, "UTC", None)
    evaluate_alerts(cfg, db, dev, "UTC", None)
    evaluate_alerts(cfg, db, dev, "UTC", None)
    assert any(
        a["rule_id"] == "battery_stuck" for a in list_alerts(db, "open"))
    db.close()


def test_no_schema_writes_on_forecast_get(tmp_path, monkeypatch):
    import server as srv

    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    db_path = tmp_path / "data" / "db.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    conn.commit()
    conn.close()
    cfg = _base_config(
        tmp_path,
        """
forecast:
  enabled: true
  latitude: 52.0
  longitude: 13.0
  min_history_days: 1
""")
    monkeypatch.setattr(srv, "config", cfg)
    before = db_path.read_bytes()
    client = srv.app.test_client()
    resp = client.get("/query?type=forecast")
    assert resp.status_code == 200
    after = db_path.read_bytes()
    assert before == after
    data = json.loads(resp.data)
    assert data["state"] in ("pending", "insufficient_history")


def test_alerts_open_not_hidden_by_resolved(tmp_path, monkeypatch):
    import server as srv

    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    old_open = datetime.now(timezone.utc) - timedelta(days=30)
    db.execute_params_no_result(
        "INSERT INTO alerts (rule_id, severity, title, message, started_at, status) "
        "VALUES ('device_unreachable', 'critical', 'O', 'M', ?, 'open')",
        (old_open.isoformat(),))
    for i in range(150):
        ts = (datetime.now(timezone.utc) - timedelta(hours=i)).isoformat()
        db.execute_params_no_result(
            "INSERT INTO alerts (rule_id, severity, title, message, started_at, "
            "ended_at, status) VALUES ('x', 'info', 't', 'm', ?, ?, 'resolved')",
            (ts, ts))
    db.close()
    monkeypatch.setattr(srv, "config", _base_config(tmp_path, "alerts:\n  enabled: true\n"))
    client = srv.app.test_client()
    resp = client.get("/query?type=alerts&status=list")
    data = json.loads(resp.data)
    assert data["open_count"] == 1
    assert any(a["status"] == "open" for a in data["open_alerts"])
    db.close()


def test_malformed_open_meteo_does_not_break_grabber_cadence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    start = date.today() - timedelta(days=5)
    for i in range(5):
        d = (start + timedelta(days=i)).isoformat()
        db.execute_params_no_result(
            "INSERT INTO days VALUES (?, 0, 5, 0, 3, 0, 1)", (d,))
    db.close()
    cfg = _base_config(
        tmp_path,
        """
forecast:
  enabled: true
  latitude: 52.0
  longitude: 13.0
  min_history_days: 1
  refresh_interval_s: 300
""")
    monkeypatch.setattr(
        "forecast_service._fetch_open_meteo",
        lambda *_a, **_k: {"hourly": "not-a-dict"})
    times = []
    stop = threading.Event()

    def heartbeat_loop():
        while not stop.is_set():
            db = Database("data/db.sqlite")
            touch_grabber_loop_heartbeat(db)
            times.append(time.monotonic())
            db.close()
            time.sleep(0.08)

    t = threading.Thread(target=heartbeat_loop, daemon=True)
    t.start()
    time.sleep(0.25)
    t0 = time.monotonic()
    run_forecast_refresh_background(cfg, "UTC")
    elapsed = time.monotonic() - t0
    time.sleep(0.25)
    stop.set()
    t.join(timeout=2)
    gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
    assert elapsed < 0.5
    assert len(times) >= 3
    assert max(gaps) < 0.5


def test_dawn_dusk_no_false_zero_production_oslo_winter(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    cfg = _base_config(
        tmp_path,
        """
forecast:
  latitude: 59.9
  longitude: 10.7
alerts:
  enabled: true
  daylight_rules_enabled: true
  zero_production_minutes: 15
""")
    monkeypatch.setattr("alert_engine._minutes_since", lambda _iso: 999.0)
    dawn = datetime(2026, 12, 10, 8, 45, tzinfo=timezone.utc)
    monkeypatch.setattr("alert_engine.local_now", lambda _tz: dawn)
    dev = _FakeDevice(power=0.0)
    evaluate_alerts(cfg, db, dev, "UTC", None)
    evaluate_alerts(cfg, db, dev, "UTC", None)
    assert not any(
        a["rule_id"] == "zero_production_daylight"
        for a in list_alerts(db, "open"))
    db.close()
