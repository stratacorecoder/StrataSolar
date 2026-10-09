'''Retire open alerts for removed rule_ids.'''

from alert_engine import retire_obsolete_open_alerts
from db_migrate import ensure_feature_schema
from database import Database


def _boot(tmp_path):
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    return db


def test_retire_obsolete_open_alerts_resolves_and_clears_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = _boot(tmp_path)
    db.execute_params_no_result(
        "INSERT INTO alerts (rule_id, severity, title, message, started_at, status) "
        "VALUES ('counter_reset', 'warning', 'Counter reset', 'Dropped', "
        "'2026-01-01T00:00:00+00:00', 'open')")
    db.execute_params_no_result(
        "INSERT INTO alert_rule_state "
        "(rule_id, open_alert_id, condition_active) VALUES ('counter_reset', 1, 1)")
    db.connection.commit()

    retired = retire_obsolete_open_alerts(db)
    db.connection.commit()
    assert retired == ['counter_reset']
    rows = db.execute(
        "SELECT status FROM alerts WHERE rule_id='counter_reset'")
    assert rows[0][0] == 'resolved'
    state = db.execute(
        "SELECT COUNT(*) FROM alert_rule_state WHERE rule_id='counter_reset'")
    assert state[0][0] == 0

    assert retire_obsolete_open_alerts(db) == []
    db.close()


def test_ensure_feature_schema_retires_obsolete_on_existing_db(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = _boot(tmp_path)
    db.execute_params_no_result(
        "INSERT INTO alerts (rule_id, severity, title, message, started_at, status) "
        "VALUES ('negative_delta', 'warning', 'Delta', 'Msg', "
        "'2026-01-01T00:00:00+00:00', 'open')")
    db.connection.commit()
    db.close()

    db2 = Database("data/db.sqlite")
    ensure_feature_schema(db2)
    db2.connection.commit()
    row = db2.execute(
        "SELECT status FROM alerts WHERE rule_id='negative_delta'")[0][0]
    assert row == 'resolved'
    db2.close()
