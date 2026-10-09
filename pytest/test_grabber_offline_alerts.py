'''Alerts must fire when device reads fail (offline dummy).'''

import time
from datetime import datetime, timedelta, timezone

import grabber as grb
from aggregates import touch_device_success_heartbeat
from alert_engine import list_alerts, open_alert_count
from config import Config
from database import Database
from db_migrate import ensure_feature_schema


def _config(tmp_path):
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
alerts:
  enabled: true
  device_stale_min_s: 30
  evaluate_interval_s: 15
  zero_production_minutes: 15
  resolve_clear_minutes: 5
dummy:
  fault_mode: offline
"""
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return Config(str(path))


def _boot_db(tmp_path):
    (tmp_path / "data").mkdir(exist_ok=True)
    grb.create_new_db()
    db = Database("data/db.sqlite")
    old = datetime.now(timezone.utc) - timedelta(minutes=30)
    db.execute_params_no_result(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        ("device_last_success_utc", old.isoformat()))
    db.close()


def test_offline_device_triggers_unreachable_alert(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _boot_db(tmp_path)
    grb.config = _config(tmp_path)
    monkeypatch.setattr("alert_engine._minutes_since", lambda _iso: 999.0)

    mono = [1000.0]

    def fake_mono():
        mono[0] += 20.0
        return mono[0]

    monkeypatch.setattr("time.monotonic", fake_mono)
    grb._last_alert_eval_mono = 0.0

    device = None
    for _ in range(4):
        device = grb._grabber_loop_iteration(device, 5)
        time.sleep(0.05)

    db = Database("data/db.sqlite")
    assert open_alert_count(db) >= 1
    assert any(
        a["rule_id"] == "device_unreachable"
        for a in list_alerts(db, "open"))
    db.close()
