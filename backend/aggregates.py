'''Helpers for consistent energy totals from historical DB tables.

Year deltas may be up to one grabber sample interval short of the all_time
row delta at each local year boundary (energy between the last sample of
December 31 and the first sample of January 1).
'''


def deltas_from_row(row):
    '''Return produced, consumed, and fed-in deltas for a history row.'''
    produced = row[2] - row[1]
    consumed = row[4] - row[3]
    fed_in = row[6] - row[5]
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
        "SELECT COALESCE(SUM(produced_b - produced_a), 0), "
        "COALESCE(SUM(consumed_b - consumed_a), 0), "
        "COALESCE(SUM(fed_in_b - fed_in_a), 0) FROM years")[0]
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


def migrate_legacy_all_time_baseline(db):
    '''Align legacy all_time rows (_a == 0) with summed year history.

    Safe to call repeatedly; only updates when _a columns are still zero and
    year rows exist.
    '''
    row = all_time_row(db)
    if not row:
        return
    if row[1] != 0 or row[3] != 0 or row[5] != 0:
        return
    year_p, year_c, year_f = sum_years_deltas(db)
    if year_p == 0 and year_c == 0 and year_f == 0:
        return
    new_pa = row[2] - year_p
    new_ca = row[4] - year_c
    new_fa = row[6] - year_f
    db.execute_params_no_result(
        "UPDATE all_time SET "
        "produced_a = ?, produced_b = ?, "
        "consumed_a = ?, consumed_b = ?, "
        "fed_in_a = ?, fed_in_b = ? "
        "WHERE date = 'all_time'",
        (new_pa, row[2], new_ca, row[4], new_fa, row[6]))


def recorded_energy_totals(db):
    migrate_legacy_all_time_baseline(db)
    produced, consumed, fed_in = sum_years_deltas(db)
    return produced, consumed, fed_in, first_recorded_day(db)
