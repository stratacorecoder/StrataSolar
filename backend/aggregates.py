'''Helpers for consistent energy totals from historical DB tables.

Displayed lifetime totals use SUM(years) deltas (recorded history). The
all_time row may still hold raw inverter counters; a one-time grabber
migration can align its _a columns for storage consistency only.

Year deltas may be up to one grabber sample interval short of the all_time
row delta at each local year boundary (energy between the last sample of
December 31 and the first sample of January 1).

When an inverter cumulative counter decreases (replacement or reset), the
grabber preserves recorded energy in each period row (see energy_recording).

Legacy databases may contain negative row deltas from older releases; all
read paths clamp each row's delta at zero before summing or displaying.
'''

from datetime import datetime, timezone

_META_KEY = 'all_time_baseline_v1'
_GRABBER_HEARTBEAT_KEY = 'grabber_last_sample_utc'

PRODUCED_DELTA_SQL = "MAX(produced_b - produced_a, 0)"
CONSUMED_DELTA_SQL = "MAX(consumed_b - consumed_a, 0)"
FED_IN_DELTA_SQL = "MAX(fed_in_b - fed_in_a, 0)"


def deltas_from_row(row):
    '''Return produced, consumed, and fed-in deltas for a history row.'''
    produced = max(0.0, row[2] - row[1])
    consumed = max(0.0, row[4] - row[3])
    fed_in = max(0.0, row[6] - row[5])
    return produced, consumed, fed_in


def sum_table_deltas(rows):
    produced = 0.0
    consumed = 0.0
    fed_in = 0.0
    for row in rows:
        p, c, f = deltas_from_row(row)
        produced += p
        consumed += c
        fed_in += f
    return produced, consumed, fed_in


def sum_years_deltas(db):
    row = db.execute(
        f"SELECT COALESCE(SUM({PRODUCED_DELTA_SQL}), 0), "
        f"COALESCE(SUM({CONSUMED_DELTA_SQL}), 0), "
        f"COALESCE(SUM({FED_IN_DELTA_SQL}), 0) FROM years")[0]
    return float(row[0]), float(row[1]), float(row[2])


def sum_days_deltas(db):
    row = db.execute(
        f"SELECT COALESCE(SUM({PRODUCED_DELTA_SQL}), 0), "
        f"COALESCE(SUM({CONSUMED_DELTA_SQL}), 0), "
        f"COALESCE(SUM({FED_IN_DELTA_SQL}), 0) FROM days")[0]
    return float(row[0]), float(row[1]), float(row[2])


def first_recorded_day(db):
    rows = db.execute("SELECT MIN(date) FROM days")
    if not rows or rows[0][0] is None:
        return None
    return rows[0][0]


def count_recorded_days(db):
    rows = db.execute("SELECT COUNT(*) FROM days")
    return int(rows[0][0])


def all_time_row(db):
    rows = db.execute("SELECT * FROM all_time WHERE date='all_time'")
    return rows[0] if rows else None


def device_lifetime_counters(db):
    '''Latest cumulative counter readings from the inverter (all_time._b).'''
    row = all_time_row(db)
    if not row:
        return 0.0, 0.0, 0.0
    return float(row[2]), float(row[4]), float(row[6])


def _ensure_meta_table(db):
    db.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta "
        "(key TEXT PRIMARY KEY, value TEXT)")


def touch_grabber_heartbeat(db):
    _ensure_meta_table(db)
    stamp = datetime.now(timezone.utc).isoformat()
    db.execute_params_no_result(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        (_GRABBER_HEARTBEAT_KEY, stamp))


def grabber_sample_age_seconds(db):
    _ensure_meta_table(db)
    rows = db.execute_params(
        "SELECT value FROM schema_meta WHERE key = ?",
        (_GRABBER_HEARTBEAT_KEY,))
    if not rows:
        return None
    try:
        last = datetime.fromisoformat(rows[0][0])
    except ValueError:
        return None
    if last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    return (now - last).total_seconds()


def _baseline_migration_done(db):
    _ensure_meta_table(db)
    rows = db.execute_params(
        "SELECT value FROM schema_meta WHERE key = ?", (_META_KEY,))
    return bool(rows) and rows[0][0] == '1'


def _mark_baseline_migration_done(db):
    _ensure_meta_table(db)
    db.execute_params_no_result(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        (_META_KEY, '1'))


def migrate_legacy_all_time_baseline(db):
    '''One-time grabber migration: set all_time._a from year sums; never _b.

    Read-only safe to call when already done (no-op). Returns True if a write
    ran in this call.
    '''
    if _baseline_migration_done(db):
        return False
    row = all_time_row(db)
    if not row:
        _mark_baseline_migration_done(db)
        return False
    if row[1] != 0 or row[3] != 0 or row[5] != 0:
        _mark_baseline_migration_done(db)
        return False
    year_count = db.execute("SELECT COUNT(*) FROM years")[0][0]
    if year_count == 0:
        return False
    db.execute_params_no_result(
        "UPDATE all_time SET "
        f"produced_a = produced_b - ("
        f"  SELECT COALESCE(SUM({PRODUCED_DELTA_SQL}), 0) FROM years), "
        f"consumed_a = consumed_b - ("
        f"  SELECT COALESCE(SUM({CONSUMED_DELTA_SQL}), 0) FROM years), "
        f"fed_in_a = fed_in_b - ("
        f"  SELECT COALESCE(SUM({FED_IN_DELTA_SQL}), 0) FROM years) "
        "WHERE date = 'all_time' "
        "AND produced_a = 0 AND consumed_a = 0 AND fed_in_a = 0")
    _mark_baseline_migration_done(db)
    return True


def recorded_energy_totals(db):
    '''Recorded history totals (read-only; never migrates).'''
    produced, consumed, fed_in = sum_years_deltas(db)
    return produced, consumed, fed_in, first_recorded_day(db)
