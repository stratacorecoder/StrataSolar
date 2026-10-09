from aggregates import sum_years_deltas
from energy_recording import (
    counters_should_be_skipped,
    derived_energy_parts,
)
from grabber import insert_historical_values
from database import Database


def _create_history_tables(db):
    for table in ("days", "months", "years", "all_time"):
        db.execute(
            f"CREATE TABLE {table} ("
            "date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
            "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")


def _apply_sample(db, produced, consumed, fed_in, day="2026-10-09"):
    month = day[:7]
    year = day[:4]
    for table, key in (
            ("days", day), ("months", month), ("years", year),
            ("all_time", "all_time")):
        insert_historical_values(db, table, key, produced, consumed, fed_in)


def test_counters_should_be_skipped_all_zero():
    assert counters_should_be_skipped(0, 0, 0) is True


def test_counters_should_be_skipped_allows_fed_in_zero():
    assert counters_should_be_skipped(100.0, 80.0, 0) is False


def test_derived_energy_parts_clamps_negatives():
    p, c, f, self_use, grid = derived_energy_parts(0.0, 0.0, 150.0)
    assert self_use == 0.0
    assert grid == 0.0


def test_main_style_writes_latest_reading_as_b():
    db = Database(":memory:")
    _create_history_tables(db)
    for value in (10.0, 20.0, 30.0):
        _apply_sample(db, value, value, value)
    row = db.execute("SELECT * FROM years")[0]
    assert row[2] - row[1] == 20.0
    assert row[2] == 30.0


def test_meterless_partial_zero_records(tmp_path):
    db_path = tmp_path / "db.sqlite"
    db = Database(str(db_path))
    _create_history_tables(db)
    _apply_sample(db, 100.0, 80.0, 0.0)
    assert db.execute("SELECT COUNT(*) FROM years")[0][0] == 1
    assert sum_years_deltas(db)[0] == 0.0


def test_glitch_dip_counts_last_reading_as_b():
    db = Database(":memory:")
    _create_history_tables(db)
    _apply_sample(db, 1000.0, 1000.0, 1000.0)
    _apply_sample(db, 998.0, 998.0, 998.0)
    _apply_sample(db, 1000.1, 1000.1, 1000.1)
    assert abs(sum_years_deltas(db)[0] - 0.1) < 0.01
