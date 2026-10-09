import time
from datetime import datetime, timedelta, timezone

from config import Config
from database import Database
from db_migrate import ensure_feature_schema
from server_alerts import evaluate_grabber_stale_once


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
alerts:
  enabled: true
  device_stale_min_s: 30
notifications:
  enabled: true
  webhook_url: http://127.0.0.1:9/hook
"""
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return Config(str(path))


def test_grabber_stale_enqueues_outbox(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    ensure_feature_schema(db)
    old = datetime.now(timezone.utc) - timedelta(hours=1)
    db.execute_params_no_result(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        ("grabber_last_loop_utc", old.isoformat()))
    db.close()
    cfg = _cfg(tmp_path)
    monkeypatch.setattr("alert_engine._minutes_since", lambda _iso: 999.0)

    monkeypatch.setattr("alert_engine._minutes_since", lambda _iso: 999.0)
    evaluate_grabber_stale_once(cfg)
    opened = evaluate_grabber_stale_once(cfg)
    assert opened
    db = Database("data/db.sqlite")
    from notifications import enqueue_for_alerts
    enqueue_for_alerts(db, cfg, opened)
    db.connection.commit()
    rows = db.execute("SELECT COUNT(*) FROM notification_outbox")[0][0]
    assert int(rows) >= 1
    db.close()
