import pytest

from query_validation import (
    QueryValidationError,
    parse_date_prefix,
    parse_export_table,
    parse_history_date,
    parse_history_detail_date,
    parse_real_time_hours,
)


def test_parse_export_table_accepts_valid_tables():
    assert parse_export_table("days") == "days"
    assert parse_export_table("years") == "years"


def test_parse_export_table_rejects_injection():
    with pytest.raises(QueryValidationError):
        parse_export_table("days; DROP TABLE days")


def test_parse_date_prefix_accepts_valid_values():
    assert parse_date_prefix("") == ""
    assert parse_date_prefix("2026") == "2026"
    assert parse_date_prefix("2026-10") == "2026-10"
    assert parse_date_prefix("2026-10-08") == "2026-10-08"


def test_parse_date_prefix_rejects_injection():
    with pytest.raises(QueryValidationError):
        parse_date_prefix("2026' OR '1'='1")


def test_parse_date_prefix_rejects_trailing_newline():
    with pytest.raises(QueryValidationError):
        parse_date_prefix("2026\n")


def test_parse_date_prefix_rejects_unicode_digits():
    with pytest.raises(QueryValidationError):
        parse_date_prefix("٢٠٢٦")


def test_parse_history_date_all_time():
    assert parse_history_date("all_time", "all_time") == "all_time"


def test_parse_history_detail_date_years_empty():
    assert parse_history_detail_date("years", "") == ""


def test_parse_real_time_hours_range():
    assert parse_real_time_hours("0") == 0
    assert parse_real_time_hours("24") == 24
    with pytest.raises(QueryValidationError):
        parse_real_time_hours("999")
    with pytest.raises(QueryValidationError):
        parse_real_time_hours("1;DROP")
    with pytest.raises(QueryValidationError):
        parse_real_time_hours("٢")
