'''Notification outbox claims prevent duplicate delivery.'''

import threading
import time
from unittest.mock import patch

from config import Config
from database import Database
from db_migrate import ensure_feature_schema
from notifications import enqueue_for_alerts, process_outbox_once

_CALLS = []


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
notifications:
  enabled: true
  webhook_url: http://127.0.0.1:9/hook?token=SECRET
  max_attempts: 5
  claim_ttl_s: 60
"""
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return Config(str(path))


def _boot(tmp_path):
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, "
        "produced_b REAL, consumed_a REAL, consumed_b REAL, "
        "fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    db.execute_params_no_result(
        "INSERT INTO alerts (rule_id, severity, title, message, "
        "started_at, status) VALUES ('t', 'critical', 'T', 'M', "
        "'2026-01-01T00:00:00+00:00', 'open')")
    aid = db.execute("SELECT last_insert_rowid()")[0][0]
    db.connection.commit()
    db.close()
    return aid


def test_two_workers_single_delivery(tmp_path, monkeypatch):
    monkeypatch.delenv("STRATASOLAR_WEBHOOK_URL", raising=False)
    monkeypatch.chdir(tmp_path)
    aid = _boot(tmp_path)
    cfg = _cfg(tmp_path)
    db = Database("data/db.sqlite")
    enqueue_for_alerts(db, cfg, [aid])
    db.connection.commit()
    db.close()

    def slow_send(*_a, **_k):
        _CALLS.append(1)
        time.sleep(0.4)

    _CALLS.clear()
    with patch("notifications._send_webhook", side_effect=slow_send):
        threads = [
            threading.Thread(
                target=process_outbox_once, args=(cfg,), daemon=True),
            threading.Thread(
                target=process_outbox_once, args=(cfg,), daemon=True),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5.0)
    assert len(_CALLS) == 1
