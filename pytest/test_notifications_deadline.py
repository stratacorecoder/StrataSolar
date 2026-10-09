'''Per-send wall-clock deadlines and head-of-line avoidance.'''

import threading
import time
from unittest.mock import patch

import requests

from config import Config
from database import Database
from db_migrate import ensure_feature_schema
from notifications import enqueue_for_alerts, process_outbox_once


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
  webhook_url: http://127.0.0.1:9/hook
  max_attempts: 5
  claim_ttl_s: 60
"""
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return Config(str(path))


def _boot_many(tmp_path, count):
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    ids = []
    for _ in range(count):
        db.execute_params_no_result(
            "INSERT INTO alerts (rule_id, severity, title, message, "
            "started_at, status) VALUES ('t', 'critical', 'T', 'M', "
            "'2026-01-01T00:00:00+00:00', 'open')")
        ids.append(db.execute("SELECT last_insert_rowid()")[0][0])
    db.connection.commit()
    db.close()
    return ids


class _DripResponse:
    status_code = 200

    def raise_for_status(self):
        return None

    def iter_content(self, chunk_size=256):
        for _ in range(80):
            time.sleep(0.25)
            yield b"x"

    def close(self):
        return None


def test_drip_webhook_times_out_and_next_row_is_attempted(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ids = _boot_many(tmp_path, 2)
    cfg = _cfg(tmp_path)
    db = Database("data/db.sqlite")
    enqueue_for_alerts(db, cfg, ids)
    db.connection.commit()
    db.close()

    calls = []

    def fake_post(*_a, **_k):
        calls.append(1)
        return _DripResponse()

    monkeypatch.setattr(requests, "post", fake_post)
    start = time.monotonic()
    process_outbox_once(cfg)
    elapsed = time.monotonic() - start
    assert len(calls) >= 2
    assert elapsed < 60


def test_hanging_smtp_times_out(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("STRATASOLAR_SMTP_PASSWORD", "secret")
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
  webhook_url: ""
  email:
    enabled: true
    smtp_host: 127.0.0.1
    smtp_port: 9
    smtp_from: a@b.c
    smtp_to: d@e.f
    email_min_severity: warning
"""
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    cfg = Config(str(path))
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    db.execute_params_no_result(
        "INSERT INTO alerts (rule_id, severity, title, message, "
        "started_at, status) VALUES ('t', 'critical', 'T', 'M', "
        "'2026-01-01T00:00:00+00:00', 'open')")
    aid = db.execute("SELECT last_insert_rowid()")[0][0]
    db.execute_params_no_result(
        "INSERT INTO notification_outbox "
        "(alert_id, channel, created_at, next_attempt_at) "
        "VALUES (?, 'email', '2026-01-01T00:00:00+00:00', "
        "'2026-01-01T00:00:00+00:00')",
        (aid,))
    db.connection.commit()
    db.close()

    class HangSMTP:
        def __init__(self, *_a, **_k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

        def set_debuglevel(self, _level):
            return None

        def starttls(self):
            return None

        def login(self, *_a, **_k):
            return None

        def send_message(self, *_a, **_k):
            time.sleep(30)

    with patch("smtplib.SMTP", HangSMTP):
        start = time.monotonic()
        process_outbox_once(cfg)
    assert time.monotonic() - start < 25


def test_two_workers_exactly_once_with_8s_endpoint(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ids = _boot_many(tmp_path, 4)
    cfg = _cfg(tmp_path)
    db = Database("data/db.sqlite")
    enqueue_for_alerts(db, cfg, ids)
    db.connection.commit()
    db.close()

    calls = []

    def slow_send(*_a, **_k):
        calls.append(1)
        time.sleep(8)

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
            t.join(timeout=120)
    assert len(calls) == 4
