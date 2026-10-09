from energy_recording import (
    counters_should_be_skipped,
    next_history_counter_columns,
)
from grabber import insert_historical_values
from database import Database


def test_counters_should_be_skipped_all_zero():
    assert counters_should_be_skipped(0, 0, 0) is True


def test_counters_should_be_skipped_partial_zero_glitch():
    assert counters_should_be_skipped(100.0, 0, 50.0) is True
    assert counters_should_be_skipped(0, 10.0, 10.0) is True


def test_counters_should_be_skipped_normal_sample():
    assert counters_should_be_skipped(100.0, 80.0, 20.0) is False


def test_counter_reset_mid_day_rebases_without_negative_delta():
    db = Database(":memory:")
    db.execute(
        "CREATE TABLE days ("
        "date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    insert_historical_values(db, "days", "2026-10-09", 100.0, 80.0, 20.0)
    insert_historical_values(db, "days", "2026-10-09", 50.0, 40.0, 10.0)
    row = db.execute("SELECT * FROM days")[0]
    assert row[1] == 50.0 and row[2] == 50.0
    assert row[2] - row[1] == 0.0
    insert_historical_values(db, "days", "2026-10-09", 55.0, 44.0, 11.0)
    row = db.execute("SELECT * FROM days")[0]
    assert row[2] - row[1] == 5.0
    assert row[4] - row[3] == 4.0
    assert row[6] - row[5] == 1.0


def test_counter_reset_mid_year():
    db = Database(":memory:")
    db.execute(
        "CREATE TABLE years ("
        "date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    insert_historical_values(db, "years", "2026", 5000.0, 4000.0, 1000.0)
    insert_historical_values(db, "years", "2026", 120.0, 90.0, 30.0)
    row = db.execute("SELECT * FROM years")[0]
    assert row[2] - row[1] == 0.0
    insert_historical_values(db, "years", "2026", 125.0, 95.0, 32.0)
    row = db.execute("SELECT * FROM years")[0]
    assert row[2] - row[1] == 5.0


def test_partial_zero_sample_is_not_stored():
    db = Database(":memory:")
    db.execute(
        "CREATE TABLE days ("
        "date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    insert_historical_values(db, "days", "2026-10-09", 100.0, 0, 50.0)
    assert db.execute("SELECT COUNT(*) FROM days")[0][0] == 0


def test_next_history_counter_columns_monotonic():
    row = ("2026-10-09", 10.0, 20.0, 5.0, 8.0, 1.0, 2.0)
    cols = next_history_counter_columns(row, 25.0, 9.0, 3.0)
    assert cols == (10.0, 25.0, 5.0, 9.0, 1.0, 3.0)
