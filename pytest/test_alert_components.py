'''Equipment components migrate existing alerts and stay read-only in GETs.'''

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from aggregates import touch_device_success_heartbeat
from alert_catalog import ALERT_COMPONENTS
from alert_engine import _open_alert, evaluate_alerts, list_alerts
from database import Database
from db_migrate import ensure_feature_schema
from feature_settings import alerts_settings


def _legacy_db(path, feature_marker=False):
    db = Database(str(path))
    db.execute(
        "CREATE TABLE alerts (id INTEGER PRIMARY KEY, rule_id TEXT NOT NULL, "
        "severity TEXT NOT NULL, title TEXT NOT NULL, message TEXT NOT NULL, "
        "started_at TEXT NOT NULL, ended_at TEXT, acknowledged_at TEXT, "
        "status TEXT NOT NULL, detail_json TEXT)")
    if feature_marker:
        db.execute("CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT)")
        db.execute("INSERT INTO schema_meta VALUES ('features_v1_schema', '1')")
        db.execute(
            "CREATE TABLE alert_rule_state (rule_id TEXT PRIMARY KEY, "
            "open_alert_id INTEGER, condition_active INTEGER, "
            "condition_since TEXT, last_value_json TEXT)")
        db.execute(
            "CREATE TABLE notification_outbox (id INTEGER PRIMARY KEY, "
            "alert_id INTEGER, channel TEXT, created_at TEXT, "
            "next_attempt_at TEXT, attempts INTEGER, last_error TEXT)")
    return db


@pytest.mark.parametrize('feature_marker', [False, True])
def test_component_migration_backfills_open_and_resolved_and_is_idempotent(
        tmp_path, feature_marker):
    db = _legacy_db(tmp_path / 'legacy.sqlite', feature_marker)
    for i, (rule, component) in enumerate(ALERT_COMPONENTS.items(), 1):
        status = 'open' if i % 2 else 'resolved'
        db.execute_params_no_result(
            "INSERT INTO alerts VALUES (?, ?, 'warning', 'Title', 'Message', "
            "'2026-04-15T04:00:00+00:00', NULL, 'ack', ?, '{\"x\":1}')",
            (i, rule, status))
    db.execute(
        "INSERT INTO alerts VALUES (100, 'legacy_unknown', 'info', 'T', 'M', "
        "'2026-04-15', '2026-04-16', NULL, 'resolved', NULL)")
    before = db.execute("SELECT * FROM alerts ORDER BY id")
    ensure_feature_schema(db)
    after = db.execute("SELECT * FROM alerts ORDER BY id")
    assert [row[:10] for row in after] == before
    assert [row[10] for row in after] == list(ALERT_COMPONENTS.values()) + ['system']
    ensure_feature_schema(db)
    assert db.execute("SELECT * FROM alerts ORDER BY id") == after
    assert all(a['component'] in {'battery', 'panels', 'inverter', 'system'}
               for a in list_alerts(db))
    with pytest.raises(Exception, match='CHECK constraint'):
        db.execute("UPDATE alerts SET component='weather' WHERE id=1")
    db.close()


def test_component_migration_concurrent_startups(tmp_path):
    path = tmp_path / 'shared.sqlite'
    db = _legacy_db(path, True)
    db.close()

    def startup(_):
        connection = Database(str(path))
        try:
            ensure_feature_schema(connection)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(startup, range(2)))
    db = Database(str(path))
    assert sum(r[1] == 'component' for r in db.execute('PRAGMA table_info(alerts)')) == 1
    db.close()


def test_each_new_alert_stores_its_component():
    db = Database(':memory:')
    ensure_feature_schema(db)
    for rule, expected in ALERT_COMPONENTS.items():
        aid = _open_alert(db, rule, 'T', 'M')
        assert db.execute_params(
            'SELECT component FROM alerts WHERE id=?', (aid,))[0][0] == expected
    db.close()


def test_migration_classifies_inserts_from_an_older_grabber():
    db = Database(':memory:')
    ensure_feature_schema(db)
    for rule, expected in ALERT_COMPONENTS.items():
        db.execute_params_no_result(
            "INSERT INTO alerts (rule_id, severity, title, message, started_at, status) "
            "VALUES (?, 'warning', 'T', 'M', '2026-04-15', 'open')", (rule,))
        assert db.execute(
            'SELECT component FROM alerts ORDER BY id DESC LIMIT 1')[0][0] == expected
    db.close()


@pytest.mark.parametrize('migrated', [False, True])
def test_alerts_get_has_components_without_writing(tmp_path, monkeypatch, migrated):
    import server as srv

    (tmp_path / 'data').mkdir()
    path = tmp_path / 'data/db.sqlite'
    db = _legacy_db(path)
    db.execute(
        "INSERT INTO alerts VALUES (1, 'battery_low_soc', 'warning', 'T', 'M', "
        "'2026-04-15', NULL, NULL, 'open', NULL)")
    db.execute(
        "INSERT INTO alerts VALUES (2, 'device_unreachable', 'critical', 'T', 'M', "
        "'2026-04-15', '2026-04-16', NULL, 'resolved', NULL)")
    if migrated:
        ensure_feature_schema(db)
    db.close()
    before = path.read_bytes()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(srv, 'config', SimpleNamespace(config_data={
        'alerts': {'enabled': True}, 'grabber': {'interval_s': 60}}))
    client = srv.app.test_client()
    for query in ('/query?type=alerts&status=list', '/query?type=alerts&status=open'):
        response = client.get(query)
        assert response.status_code == 200
        payload = json.loads(response.data)
        assert payload['state'] == 'ok'
        assert payload['open_alerts'][0]['component'] == 'battery'
        if payload.get('recent_resolved'):
            assert payload['recent_resolved'][0]['component'] == 'inverter'
        assert path.read_bytes() == before


def test_consumption_spike_is_opt_in_and_disabled_rule_resolves(monkeypatch):
    db = Database(':memory:')
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    touch_device_success_heartbeat(db)
    today = datetime.now(timezone.utc).date()
    for offset in range(1, 8):
        db.execute_params_no_result(
            "INSERT INTO days VALUES (?, 0, 20, 0, 5, 0, 0)",
            ((today - timedelta(days=offset)).isoformat(),))
    db.execute_params_no_result(
        "INSERT INTO days VALUES (?, 0, 20, 0, 50, 0, 0)", (today.isoformat(),))
    cfg = SimpleNamespace(config_data={'grabber': {'interval_s': 60}})
    dev = SimpleNamespace(current_power_produced_kw=3)
    monkeypatch.setattr('alert_engine.local_now', lambda _: datetime(
        today.year, today.month, today.day, 15, tzinfo=timezone.utc))
    monkeypatch.setattr('alert_engine._minutes_since', lambda _: 999)
    assert alerts_settings(cfg.config_data)['consumption_spike_enabled'] is False
    for _ in range(2):
        evaluate_alerts(cfg, db, dev, 'UTC')
    assert not any(a['rule_id'] == 'consumption_spike' for a in list_alerts(db))
    cfg.config_data['alerts'] = {'consumption_spike_enabled': True}
    for _ in range(2):
        evaluate_alerts(cfg, db, dev, 'UTC')
    assert any(a['rule_id'] == 'consumption_spike' for a in list_alerts(db, 'open'))
    cfg.config_data['alerts']['consumption_spike_enabled'] = False
    for _ in range(2):
        evaluate_alerts(cfg, db, dev, 'UTC')
    assert not any(a['rule_id'] == 'consumption_spike' for a in list_alerts(db, 'open'))
    db.close()
