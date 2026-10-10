'''Safe schema migrations for forecast and alert features.'''

from aggregates import _ensure_meta_table
from alert_catalog import ALERT_COMPONENTS

_MIGRATION_KEY = 'features_v1_schema'


def ensure_feature_schema(db):
    '''Create forecast/alert tables if missing; safe on fresh and legacy DBs.'''
    _ensure_meta_table(db)
    rows = db.execute_params(
        "SELECT value FROM schema_meta WHERE key = ?", (_MIGRATION_KEY,))
    if rows and rows[0][0] == '1':
        _ensure_alert_components(db)
        _ensure_outbox_claim_columns(db)
        _purge_notification_outbox(db)
        from alert_engine import retire_obsolete_open_alerts
        retire_obsolete_open_alerts(db)
        return

    db.execute(
        "CREATE TABLE IF NOT EXISTS forecast_cache ("
        "id INTEGER PRIMARY KEY CHECK (id = 1), "
        "updated_at TEXT, source TEXT, payload TEXT)")

    db.execute(
        "CREATE TABLE IF NOT EXISTS forecast_accuracy ("
        "date TEXT PRIMARY KEY, "
        "predicted_production_kwh REAL, "
        "actual_production_kwh REAL, "
        "predicted_consumption_kwh REAL, "
        "actual_consumption_kwh REAL)")

    db.execute(
        "CREATE TABLE IF NOT EXISTS alerts ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "rule_id TEXT NOT NULL, "
        "severity TEXT NOT NULL, "
        "title TEXT NOT NULL, "
        "message TEXT NOT NULL, "
        "started_at TEXT NOT NULL, "
        "ended_at TEXT, "
        "acknowledged_at TEXT, "
        "status TEXT NOT NULL, "
        "detail_json TEXT, "
        "component TEXT NOT NULL DEFAULT 'system' "
        "CHECK (component IN ('battery', 'panels', 'inverter', 'system')))")

    db.execute(
        "CREATE INDEX IF NOT EXISTS idx_alerts_status "
        "ON alerts(status, started_at DESC)")

    db.execute(
        "CREATE TABLE IF NOT EXISTS alert_rule_state ("
        "rule_id TEXT PRIMARY KEY, "
        "open_alert_id INTEGER, "
        "condition_active INTEGER NOT NULL DEFAULT 0, "
        "condition_since TEXT, "
        "last_value_json TEXT)")

    db.execute(
        "CREATE TABLE IF NOT EXISTS notification_outbox ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "alert_id INTEGER NOT NULL, "
        "channel TEXT NOT NULL, "
        "created_at TEXT NOT NULL, "
        "next_attempt_at TEXT NOT NULL, "
        "attempts INTEGER NOT NULL DEFAULT 0, "
        "last_error TEXT, "
        "claimed_until TEXT, "
        "claim_owner TEXT, "
        "failed_at TEXT)")

    _ensure_outbox_claim_columns(db)
    _ensure_alert_components(db)

    db.execute_params_no_result(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        (_MIGRATION_KEY, '1'))

    _purge_notification_outbox(db)
    from alert_engine import retire_obsolete_open_alerts
    retire_obsolete_open_alerts(db)


def _ensure_alert_components(db):
    # Acquire the SQLite writer lock before inspecting/altering the schema.
    # Concurrent grabber/server startups must not both attempt ADD COLUMN.
    key = 'alerts_component_v1'
    db.execute_params_no_result(
        "INSERT OR IGNORE INTO schema_meta (key, value) VALUES (?, '0')",
        (key,))
    names = {row[1] for row in db.execute("PRAGMA table_info(alerts)")}
    if 'component' not in names:
        db.execute(
            "ALTER TABLE alerts ADD COLUMN component TEXT NOT NULL "
            "DEFAULT 'system' CHECK (component IN "
            "('battery', 'panels', 'inverter', 'system'))")
    # An older grabber may still be running while the server migrates. Its
    # INSERT omits component; classify those rows too, without any GET writes.
    cases = ' '.join(f"WHEN '{rule}' THEN '{component}'"
                     for rule, component in ALERT_COMPONENTS.items())
    # Recreate on every run so the rule->component CASE always matches this code.
    db.execute("DROP TRIGGER IF EXISTS alerts_component_insert")
    db.execute(
        "CREATE TRIGGER alerts_component_insert AFTER INSERT ON alerts "
        "WHEN NEW.component='system' BEGIN UPDATE alerts SET component=CASE NEW.rule_id "
        + cases + " ELSE 'system' END WHERE id=NEW.id; END")
    # Backfill open and resolved rows, preserving every other field and id.
    for rule_id, component in ALERT_COMPONENTS.items():
        db.execute_params_no_result(
            "UPDATE alerts SET component=? WHERE rule_id=? "
            "AND component != ?", (component, rule_id, component))
    db.execute_params_no_result(
        "UPDATE schema_meta SET value='1' WHERE key=?", (key,))


def _purge_notification_outbox(db):
    try:
        db.execute("DELETE FROM notification_outbox")
    except Exception:
        pass


def _ensure_outbox_claim_columns(db):
    rows = db.execute("PRAGMA table_info(notification_outbox)")
    names = {row[1] for row in rows}
    if 'claimed_until' not in names:
        db.execute(
            "ALTER TABLE notification_outbox ADD COLUMN claimed_until TEXT")
    if 'claim_owner' not in names:
        db.execute(
            "ALTER TABLE notification_outbox ADD COLUMN claim_owner TEXT")
    if 'failed_at' not in names:
        db.execute(
            "ALTER TABLE notification_outbox ADD COLUMN failed_at TEXT")
