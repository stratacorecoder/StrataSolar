'''Safe schema migrations for forecast and alert features.'''

from aggregates import _ensure_meta_table

_MIGRATION_KEY = 'features_v1_schema'


def ensure_feature_schema(db):
    '''Create forecast/alert tables if missing; safe on fresh and legacy DBs.'''
    _ensure_meta_table(db)
    rows = db.execute_params(
        "SELECT value FROM schema_meta WHERE key = ?", (_MIGRATION_KEY,))
    if rows and rows[0][0] == '1':
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
        "detail_json TEXT)")

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
        "last_error TEXT)")

    db.execute_params_no_result(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        (_MIGRATION_KEY, '1'))
