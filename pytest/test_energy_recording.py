from aggregates import sum_years_deltas
from energy_recording import (
    counters_should_be_skipped,
    next_history_counter_columns,
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


def _year_produced(db):
    return sum_years_deltas(db)[0]


def test_counters_should_be_skipped_all_zero():
    assert counters_should_be_skipped(0, 0, 0) is True


def test_counters_should_be_skipped_allows_fed_in_zero():
    assert counters_should_be_skipped(100.0, 80.0, 0) is False


def test_counter_jitter_within_tolerance_ignored():
    row = ("2026", 0.0, 1010.0, 0.0, 800.0, 0.0, 200.0)
    pa, pb, *_rest, reset = next_history_counter_columns(
        row, 1009.999, 800.0, 200.0)
    assert reset is False
    assert pb == 1010.0
    pa2, pb2, *_r2, reset2 = next_history_counter_columns(
        (row[0], pa, pb, row[3], row[4], row[5], row[6]),
        1015.0, 805.0, 205.0)
    assert reset2 is False
    assert pb2 == 1015.0
    assert pb2 - pa == 1015.0 - pa


def test_counter_reset_mid_year_preserves_recorded_energy():
    db = Database(":memory:")
    _create_history_tables(db)
    for value in (10, 20, 30, 40, 50):
        _apply_sample(db, float(value), float(value), float(value), "2026-01-15")
    before = _year_produced(db)
    assert before == 40.0
    _apply_sample(db, 5.0, 5.0, 5.0, "2026-01-15")
    after_swap = _year_produced(db)
    assert after_swap == before
    _apply_sample(db, 10.0, 10.0, 10.0, "2026-01-15")
    assert _year_produced(db) == before + 5.0


def test_inverter_swap_scenario_preserves_then_counts_once():
    db = Database(":memory:")
    _create_history_tables(db)
    for value in range(10, 931, 10):
        _apply_sample(db, float(value), float(value), float(value))
    assert _year_produced(db) == 920.0
    _apply_sample(db, 5.0, 5.0, 5.0)
    assert _year_produced(db) == 920.0
    _apply_sample(db, 8.0, 8.0, 8.0)
    assert _year_produced(db) == 923.0


def test_jitter_then_recovery_matches_main_style_total():
    db = Database(":memory:")
    _create_history_tables(db)
    for value in range(10, 1011, 10):
        _apply_sample(db, float(value), float(value), float(value))
    _apply_sample(db, 1009.999, 1009.999, 1009.999)
    _apply_sample(db, 1015.0, 1015.0, 1015.0)
    assert _year_produced(db) == 1005.0


def test_consumed_only_reset_preserves_consumed_delta():
    db = Database(":memory:")
    _create_history_tables(db)
    _apply_sample(db, 1000.0, 100.0, 500.0)
    _apply_sample(db, 1010.0, 2005.0, 510.0)
    _apply_sample(db, 1010.0, 4.0, 510.0)
    row = db.execute("SELECT * FROM years")[0]
    assert row[2] - row[1] == 10.0
    assert row[4] - row[3] == 1905.0


def test_fronius_style_consumed_dip_within_tolerance():
    db = Database(":memory:")
    _create_history_tables(db)
    _apply_sample(db, 6000.0, 5700.0, 1000.0)
    _apply_sample(db, 6000.25, 5699.75, 1000.25)
    assert db.execute("SELECT * FROM years")[0][4] - db.execute(
        "SELECT * FROM years")[0][3] == 0.0


def test_reset_first_sample_of_day_preserves_month_and_year():
    db = Database(":memory:")
    _create_history_tables(db)
    for value in range(10, 911, 10):
        _apply_sample(db, float(value), float(value), float(value), "2026-10-08")
    year_delta_before = db.execute("SELECT * FROM years")[0]
    year_delta_before = year_delta_before[2] - year_delta_before[1]
    month_delta_before = db.execute("SELECT * FROM months")[0]
    month_delta_before = month_delta_before[2] - month_delta_before[1]
    _apply_sample(db, 5.0, 5.0, 5.0, "2026-10-09")
    day_row = db.execute("SELECT * FROM days WHERE date='2026-10-09'")[0]
    assert day_row[2] - day_row[1] == 0.0
    month_row = db.execute("SELECT * FROM months")[0]
    year_row = db.execute("SELECT * FROM years")[0]
    assert month_row[2] - month_row[1] == month_delta_before
    assert year_row[2] - year_row[1] == year_delta_before


def test_meterless_partial_zero_records(tmp_path, monkeypatch):
    db_path = tmp_path / "db.sqlite"
    db = Database(str(db_path))
    _create_history_tables(db)
    _apply_sample(db, 100.0, 80.0, 0.0)
    assert db.execute("SELECT COUNT(*) FROM years")[0][0] == 1
    assert _year_produced(db) == 0.0


def test_glitch_dip_double_count_avoided():
    db = Database(":memory:")
    _create_history_tables(db)
    _apply_sample(db, 1000.0, 1000.0, 1000.0)
    _apply_sample(db, 998.0, 998.0, 998.0)
    _apply_sample(db, 1000.1, 1000.1, 1000.1)
    assert abs(_year_produced(db) - 0.1) < 0.01


def test_repeated_resets_preserve_cumulative_delta():
    db = Database(":memory:")
    _create_history_tables(db)
    _apply_sample(db, 500.0, 500.0, 500.0)
    _apply_sample(db, 5.0, 5.0, 5.0)
    _apply_sample(db, 3.0, 3.0, 3.0)
    _apply_sample(db, 10.0, 10.0, 10.0)
    assert _year_produced(db) == 5.0


def test_restart_reads_preserved_totals(tmp_path):
    db_path = tmp_path / "db.sqlite"
    db = Database(str(db_path))
    _create_history_tables(db)
    _apply_sample(db, 500.0, 500.0, 500.0)
    _apply_sample(db, 5.0, 5.0, 5.0)
    db.close()
    db2 = Database(str(db_path))
    assert _year_produced(db2) == 0.0
    _apply_sample(db2, 10.0, 10.0, 10.0)
    assert _year_produced(db2) == 5.0
    db2.close()
