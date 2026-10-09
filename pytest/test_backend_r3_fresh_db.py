'''Fresh-install DB race: server must not create empty sqlite files.'''

import threading
import time
import pytest

from database import Database, DatabaseMissingError, open_database
from grabber import ensure_grabber_database
from server_alerts import evaluate_grabber_stale_once


def _minimal_config(tmp_path):
    from config import Config
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
"""
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return Config(str(path))


def test_server_alerts_does_not_create_database(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    cfg = _minimal_config(tmp_path)
    evaluate_grabber_stale_once(cfg)
    assert not (tmp_path / "data" / "db.sqlite").exists()


def test_empty_sqlite_file_repaired_by_grabber(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "db.sqlite").write_bytes(b"")
    ensure_grabber_database()
    db = Database("data/db.sqlite")
    rows = db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='all_time'")
    assert rows
    db.close()


def test_server_first_then_grabber(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    cfg = _minimal_config(tmp_path)

    def server_side():
        for _ in range(20):
            evaluate_grabber_stale_once(cfg)
            time.sleep(0.05)

    t = threading.Thread(target=server_side, daemon=True)
    t.start()
    time.sleep(0.25)
    ensure_grabber_database()
    t.join(timeout=2.0)
    db = Database("data/db.sqlite")
    assert db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='all_time'")
    db.close()


def test_open_database_create_false_missing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    with pytest.raises(DatabaseMissingError):
        open_database(create=False)
