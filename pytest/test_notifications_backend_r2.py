'''Notification outbox must not hold DB locks across network I/O.'''

import logging
import threading
import time
from unittest.mock import patch

from config import Config
from database import Database
from db_migrate import ensure_feature_schema
from notifications import (
    _safe_delivery_error,
    enqueue_for_alerts,
    process_outbox_once,
)


def _cfg(tmp_path, extra=""):
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
notifications:
  enabled: true
  webhook_url: http://127.0.0.1:9/hook?token=SECRETTOKEN99
{extra}
"""
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return Config(str(path))


def test_hanging_webhook_does_not_block_concurrent_db_write(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    db.execute_params_no_result(
        "INSERT INTO alerts (rule_id, severity, title, message, started_at, status) "
        "VALUES ('test', 'critical', 'T', 'M', '2026-01-01T00:00:00+00:00', 'open')")
    aid = db.execute("SELECT last_insert_rowid()")[0][0]
    cfg = _cfg(tmp_path)
    enqueue_for_alerts(db, cfg, [aid])
    db.connection.commit()
    db.close()

    def hang(*_a, **_k):
        time.sleep(2.0)

    errors = []
    done = threading.Event()

    def writer():
        try:
            while not done.is_set():
                wdb = Database("data/db.sqlite")
                wdb.execute_params_no_result(
                    "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
                    ("writer_ping", "1"))
                wdb.connection.commit()
                wdb.close()
                time.sleep(0.05)
        except Exception as exc:
            errors.append(exc)

    monkeypatch.setattr("notifications._send_webhook", hang)
    t = threading.Thread(target=writer, daemon=True)
    t.start()
    process_outbox_once(cfg)
    done.set()
    t.join(timeout=3)
    assert not errors, errors


def test_connection_error_redacts_token_from_db_and_logs(tmp_path, caplog):
    import requests

    url = "http://127.0.0.1:9/hook?token=SECRETTOKEN99"
    exc = requests.ConnectionError(
        "HTTPConnectionPool(host='127.0.0.1', port=9): Max retries exceeded "
        "with url: /hook?token=SECRETTOKEN99 (Caused by NewConnectionError)")
    safe = _safe_delivery_error(exc, {'webhook_url': url})
    assert "SECRETTOKEN99" not in safe
    assert "ConnectionError" in safe
    with caplog.at_level(logging.WARNING):
        logging.warning("Notification delivery failed (id=%s): %s", 1, safe)
    assert "SECRETTOKEN99" not in caplog.text
