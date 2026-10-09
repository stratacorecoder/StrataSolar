'''Helpers for consistent energy totals from historical DB tables.'''


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


def recorded_totals_from_years(db):
    rows = db.execute(
        "SELECT date, produced_a, produced_b, consumed_a, consumed_b, "
        "fed_in_a, fed_in_b FROM years ORDER BY date")
    return sum_table_deltas(rows), rows


def recorded_totals_from_days(db):
    rows = db.execute(
        "SELECT date, produced_a, produced_b, consumed_a, consumed_b, "
        "fed_in_a, fed_in_b FROM days ORDER BY date")
    return sum_table_deltas(rows), rows


def history_bounds_from_days(rows):
    if not rows:
        return None, None
    dates = [row[0] for row in rows]
    return dates[0], dates[-1]
