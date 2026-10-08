import re

EXPORT_TABLES = frozenset({"days", "months", "years"})
HISTORY_TABLES = frozenset({"days", "months", "years", "all_time"})
HISTORY_DETAIL_TABLES = frozenset({"days", "months", "years"})

_DATE_DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_DATE_MONTH = re.compile(r"^\d{4}-\d{2}$")
_DATE_YEAR = re.compile(r"^\d{4}$")
_DATE_PREFIX = re.compile(r"^\d{4}(-\d{2}(-\d{2})?)?$")

REAL_TIME_HOURS_MIN = 1
REAL_TIME_HOURS_MAX = 168


class QueryValidationError(ValueError):
    """Raised when a query parameter fails validation."""


def parse_export_table(table_name):
    if table_name not in EXPORT_TABLES:
        raise QueryValidationError(f"invalid export table: {table_name}")
    return table_name


def parse_date_prefix(date_value):
    if date_value == "":
        return ""
    if not _DATE_PREFIX.match(date_value):
        raise QueryValidationError(f"invalid date prefix: {date_value}")
    return date_value


def parse_history_table(table_name):
    if table_name not in HISTORY_TABLES:
        raise QueryValidationError(f"invalid history table: {table_name}")
    return table_name


def parse_history_date(table_name, date_value):
    if table_name == "all_time":
        if date_value != "all_time":
            raise QueryValidationError("all_time table requires date=all_time")
        return date_value
    if table_name == "days":
        if not _DATE_DAY.match(date_value):
            raise QueryValidationError(f"invalid day date: {date_value}")
    elif table_name == "months":
        if not _DATE_MONTH.match(date_value):
            raise QueryValidationError(f"invalid month date: {date_value}")
    elif table_name == "years":
        if not _DATE_YEAR.match(date_value):
            raise QueryValidationError(f"invalid year date: {date_value}")
    return date_value


def parse_history_detail_date(table_name, date_value):
    if table_name not in HISTORY_DETAIL_TABLES:
        raise QueryValidationError(f"invalid history detail table: {table_name}")
    if table_name == "days" and not _DATE_MONTH.match(date_value):
        raise QueryValidationError(f"invalid month prefix: {date_value}")
    if table_name == "months" and not _DATE_YEAR.match(date_value):
        raise QueryValidationError(f"invalid year prefix: {date_value}")
    if table_name == "years" and date_value != "":
        raise QueryValidationError("years detail query does not take a date")
    return date_value


def parse_real_time_hours(hours_value):
    try:
        hours = int(hours_value)
    except (TypeError, ValueError):
        raise QueryValidationError("invalid real_time hours")
    if hours < REAL_TIME_HOURS_MIN or hours > REAL_TIME_HOURS_MAX:
        raise QueryValidationError("real_time hours out of range")
    return hours
