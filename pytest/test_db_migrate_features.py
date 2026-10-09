'''Migration from a main-branch style database to forecast/alert tables.'''

import sqlite3

from db_migrate import ensure_feature_schema
from database import Database
from grabber import create_new_db


def test_ensure_feature_schema_on_legacy_db(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "db.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    conn.execute(
        "CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.commit()
    conn.close()

    monkeypatch.chdir(tmp_path)
    db = Database("data/db.sqlite")
    ensure_feature_schema(db)
    tables = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "alerts" in tables
    assert "forecast_cache" in tables
    assert "alert_rule_state" in tables


def test_create_new_db_includes_feature_tables(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    create_new_db()
    db = Database("data/db.sqlite")
    tables = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert "forecast_accuracy" in tables
    assert "notification_outbox" in tables
