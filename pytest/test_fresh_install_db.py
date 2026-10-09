'''Fresh database bootstrap (schema_meta for grabber heartbeats).'''

from aggregates import grabber_loop_age_seconds, touch_grabber_loop_heartbeat
from grabber import create_new_db
from database import Database


def test_create_new_db_includes_schema_meta(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    monkeypatch.chdir(tmp_path)
    create_new_db()
    db = Database("data/db.sqlite")
    rows = db.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type='table' AND name='schema_meta'")
    assert rows
    touch_grabber_loop_heartbeat(db)
    assert grabber_loop_age_seconds(db) is not None
