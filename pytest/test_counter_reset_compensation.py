'''Counter reset compensation (default 15 min, 3 samples).'''

from aggregates import sum_years_deltas
from database import Database
from grabber import init_counter_compensator, insert_historical_values


def _create_history_tables(db):
    for table in ("days", "months", "years", "all_time"):
        db.execute(
            f"CREATE TABLE {table} ("
            "date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
            "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")


def _init_defaults(clock):
    init_counter_compensator({
        'interval_s': 5,
    }, clock=lambda: clock[0])


def _apply_poll(db, clock, produced, consumed, fed_in, day="2026-10-09",
                advance_s=301):
    clock[0] += advance_s
    from grabber import _compensator
    comp = _compensator()
    comp.begin_poll(sample_time=clock[0])
    month, year = day[:7], day[:4]
    for table, key in (
            ("days", day), ("months", month), ("years", year),
            ("all_time", "all_time")):
        insert_historical_values(db, table, key, produced, consumed, fed_in)
    comp.finish_poll()


def _low_polls(db, clock, value, times=3, day="2026-10-09"):
    for _ in range(times):
        _apply_poll(db, clock, value, value, value, day=day)


def test_swap_at_90_percent_preserves_then_counts():
    db = Database(":memory:")
    _create_history_tables(db)
    clock = [1_000_000.0]
    _init_defaults(clock)
    _apply_poll(db, clock, 10000.0, 10000.0, 10000.0)
    _low_polls(db, clock, 9000.0)
    assert sum_years_deltas(db)[0] == 0.0
    _apply_poll(db, clock, 9900.0, 9900.0, 9900.0)
    assert abs(sum_years_deltas(db)[0] - 900.0) < 0.01


def test_single_zero_on_fed_in_not_a_reset():
    db = Database(":memory:")
    _create_history_tables(db)
    clock = [1_000_000.0]
    _init_defaults(clock)
    _apply_poll(db, clock, 1000.0, 1000.0, 5000.0)
    _apply_poll(db, clock, 1005.0, 1005.0, 0.0)
    _apply_poll(db, clock, 1010.0, 1010.0, 5005.0)
    row = db.execute("SELECT * FROM years")[0]
    assert abs((row[6] - row[5]) - 5.0) < 0.01


def test_legit_100_kwh_step_not_capped():
    db = Database(":memory:")
    _create_history_tables(db)
    clock = [1_000_000.0]
    _init_defaults(clock)
    _apply_poll(db, clock, 1000.0, 1000.0, 1000.0)
    _apply_poll(db, clock, 1100.0, 1100.0, 1100.0)
    assert abs(sum_years_deltas(db)[0] - 100.0) < 0.01


def test_glitch_dip_recovers_without_extra_delta():
    db = Database(":memory:")
    _create_history_tables(db)
    clock = [1_000_000.0]
    _init_defaults(clock)
    _apply_poll(db, clock, 1000.0, 1000.0, 1000.0)
    _apply_poll(db, clock, 998.0, 998.0, 998.0, advance_s=5)
    _apply_poll(db, clock, 1000.1, 1000.1, 1000.1, advance_s=5)
    assert abs(sum_years_deltas(db)[0] - 0.1) < 0.01


def test_restart_mid_confirmation(tmp_path):
    db_path = tmp_path / "db.sqlite"
    db = Database(str(db_path))
    _create_history_tables(db)
    clock = [1_000_000.0]
    _init_defaults(clock)
    _apply_poll(db, clock, 500.0, 500.0, 500.0)
    _apply_poll(db, clock, 5.0, 5.0, 5.0)
    from grabber import _compensator
    _compensator().save_persisted(db)
    db.close()
    clock[0] += 301
    _init_defaults(clock)
    from aggregates import _ensure_meta_table
    db2 = Database(str(db_path))
    _ensure_meta_table(db2)
    _compensator().load_persisted(db2)
    _low_polls(db2, clock, 5.0, times=2)
    _apply_poll(db2, clock, 10.0, 10.0, 10.0)
    assert abs(sum_years_deltas(db2)[0] - 5.0) < 0.01


def test_swap_at_30_percent_counts_after_confirm():
    db = Database(":memory:")
    _create_history_tables(db)
    clock = [1_000_000.0]
    _init_defaults(clock)
    _apply_poll(db, clock, 10000.0, 10000.0, 10000.0)
    _low_polls(db, clock, 3000.0)
    _apply_poll(db, clock, 4000.0, 4000.0, 4000.0)
    assert abs(sum_years_deltas(db)[0] - 1000.0) < 0.01


def test_swap_at_60_percent_counts_after_confirm():
    db = Database(":memory:")
    _create_history_tables(db)
    clock = [1_000_000.0]
    _init_defaults(clock)
    _apply_poll(db, clock, 10000.0, 10000.0, 10000.0)
    _low_polls(db, clock, 6000.0)
    _apply_poll(db, clock, 6500.0, 6500.0, 6500.0)
    assert abs(sum_years_deltas(db)[0] - 500.0) < 0.01


def test_day_rollover_does_not_clear_month_pending():
    db = Database(":memory:")
    _create_history_tables(db)
    clock = [1_000_000.0]
    _init_defaults(clock)
    for value in (100.0, 200.0, 300.0):
        _apply_poll(db, clock, value, value, value, day="2026-10-08")
    month_before = db.execute("SELECT * FROM months")[0]
    month_before = month_before[2] - month_before[1]
    _apply_poll(db, clock, 5.0, 5.0, 5.0, day="2026-10-08")
    _apply_poll(db, clock, 5.0, 5.0, 5.0, day="2026-10-09")
    _low_polls(db, clock, 5.0, times=1, day="2026-10-09")
    _apply_poll(db, clock, 10.0, 10.0, 10.0, day="2026-10-09")
    month_after = db.execute("SELECT * FROM months")[0]
    assert month_after[2] - month_after[1] == month_before + 5.0


def test_invalid_config_rejects_non_positive_samples():
    from energy_recording import CounterResetSettings
    from config import ConfigError
    try:
        CounterResetSettings({'counter_reset_confirm_samples': 0})
        assert False, 'expected ConfigError'
    except ConfigError:
        pass
