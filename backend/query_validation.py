import re

EXPORT_TABLES = frozenset({"days", "months", "years"})
HISTORY_TABLES = frozenset({"days", "months", "years", "all_time"})
HISTORY_DETAIL_TABLES = frozenset({"days", "months", "years"})
QUERY_TYPES = frozenset({
    "current",
    "dates",
    "historical",
    "real_time",
    "days_in_month",
    "months_in_year",
    "years_in_all_time",
    "statistics",
})

_ASCII = re.ASCII
_DATE_DAY = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", _ASCII)
_DATE_MONTH = re.compile(r"[0-9]{4}-[0-9]{2}", _ASCII)
_DATE_YEAR = re.compile(r"[0-9]{4}", _ASCII)
_DATE_PREFIX = re.compile(r"[0-9]{4}(-[0-9]{2}(-[0-9]{2})?)?", _ASCII)
_REAL_TIME_HOURS_TEXT = re.compile(r"[0-9]{1,3}", _ASCII)

REAL_TIME_HOURS_MIN = 0
REAL_TIME_HOURS_MAX = 168


class QueryValidationError(ValueError):
    """Raised when a query parameter fails validation."""


def parse_query_type(type_value):
    if type_value not in QUERY_TYPES:
        raise QueryValidationError(f"invalid query type: {type_value}")
    return type_value


def parse_export_table(table_name):
    if table_name not in EXPORT_TABLES:
        raise QueryValidationError(f"invalid export table: {table_name}")
    return table_name


def parse_date_prefix(date_value):
    if date_value == "":
        return ""
    if _DATE_PREFIX.fullmatch(date_value) is None:
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
        if _DATE_DAY.fullmatch(date_value) is None:
            raise QueryValidationError(f"invalid day date: {date_value}")
    elif table_name == "months":
        if _DATE_MONTH.fullmatch(date_value) is None:
            raise QueryValidationError(f"invalid month date: {date_value}")
    elif table_name == "years":
        if _DATE_YEAR.fullmatch(date_value) is None:
            raise QueryValidationError(f"invalid year date: {date_value}")
    return date_value


def parse_history_detail_date(table_name, date_value):
    if table_name not in HISTORY_DETAIL_TABLES:
        raise QueryValidationError(f"invalid history detail table: {table_name}")
    if table_name == "days" and _DATE_MONTH.fullmatch(date_value) is None:
        raise QueryValidationError(f"invalid month prefix: {date_value}")
    if table_name == "months" and _DATE_YEAR.fullmatch(date_value) is None:
        raise QueryValidationError(f"invalid year prefix: {date_value}")
    if table_name == "years" and date_value != "":
        raise QueryValidationError("years detail query does not take a date")
    return date_value


def parse_real_time_hours(hours_value):
    if _REAL_TIME_HOURS_TEXT.fullmatch(hours_value) is None:
        raise QueryValidationError("invalid real_time hours")
    try:
        hours = int(hours_value)
    except ValueError:
        raise QueryValidationError("invalid real_time hours")
    if hours < REAL_TIME_HOURS_MIN or hours > REAL_TIME_HOURS_MAX:
        raise QueryValidationError("real_time hours out of range")
    return hours
