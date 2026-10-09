'''Fronius E_Total updates ~5 min; meter export updates every poll.'''

from aggregates import sum_years_deltas
from grabber import insert_historical_values
from database import Database


def _create_history_tables(db):
    for table in ("days", "months", "years", "all_time"):
        db.execute(
            f"CREATE TABLE {table} ("
            "date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
            "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")


def _run_stale_etotal_hour(export_kw, polls=240, interval_s=15):
    db = Database(":memory:")
    _create_history_tables(db)
    produced = 6000.0
    fed_in = 1000.0
    grid = 5500.0
    true_consumed = produced + grid - fed_in
    cons_step = 1.0 / polls

    for poll in range(polls):
        fed_in += export_kw * (interval_s / 3600.0)
        true_consumed += cons_step
        if poll % 20 == 19:
            produced += cons_step + export_kw * (20 * interval_s / 3600.0)
            consumed = true_consumed
        else:
            consumed = true_consumed - export_kw * (
                (poll % 20 + 1) * interval_s / 3600.0)
        insert_historical_values(
            db, "years", "2026", produced, consumed, fed_in)
    return sum_years_deltas(db)[1], 1.0


def test_fronius_export_3_and_6_kw_consumption_about_one_kwh():
    for export_kw in (3, 6):
        recorded, expected = _run_stale_etotal_hour(export_kw)
        assert abs(recorded - expected) < 0.15


def test_fronius_export_8_and_10_kw_consumption_about_one_kwh():
    for export_kw in (8, 10):
        recorded, expected = _run_stale_etotal_hour(export_kw)
        assert abs(recorded - expected) < 0.15
