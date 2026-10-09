import logging
import os
import re
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_invalid_tz_warned = False

_POSIX_MAX_LEN = 64
_POSIX_NAME = r"(?:<[+-]?[A-Za-z0-9]+>|[A-Za-z]{3,})"
_POSIX_OFFSET = r"[+-]?(?:\d|1\d|2[0-3])(?::[0-5]\d){0,2}"
_POSIX_RULE = (
    r"(?:"
    r"M(?:1[0-2]|[1-9])\.[1-5]\.[0-6]"
    r"|J?\d{1,3}"
    r")"
    r"(?:/[+-]?\d{1,3}(?::[0-5]\d){0,2})?"
)
_POSIX_TIME_ZONE = re.compile(
    rf"^{_POSIX_NAME}{_POSIX_OFFSET}"
    rf"(?:{_POSIX_NAME}(?:{_POSIX_OFFSET})?)?"
    rf"(?:,{_POSIX_RULE},{_POSIX_RULE})?"
    rf"$"
)
_IANA_REGION_CITY = re.compile(r"^[A-Za-z_+-]+/[A-Za-z_+-]+$")


def normalize_time_zone(time_zone_name):
    if time_zone_name is None or not isinstance(time_zone_name, str):
        return time_zone_name
    return time_zone_name.strip()


def _warn_invalid_time_zone(time_zone_name, message):
    global _invalid_tz_warned
    if not _invalid_tz_warned:
        logging.warning(
            "Invalid time_zone '%s' (%s); using UTC",
            time_zone_name, message)
        _invalid_tz_warned = True


def _is_posix_time_zone(time_zone_name):
    if not time_zone_name or len(time_zone_name) > _POSIX_MAX_LEN:
        return False
    if _IANA_REGION_CITY.match(time_zone_name):
        return False
    return _POSIX_TIME_ZONE.match(time_zone_name) is not None


def _utc_now():
    return datetime.now(timezone.utc)


def _process_local_now(time_zone_name):
    '''Local wall time from the process TZ; UTC if libc/Python rejects it.'''
    try:
        return datetime.now().astimezone()
    except (ValueError, OverflowError) as exc:
        _warn_invalid_time_zone(time_zone_name, str(exc))
        return _utc_now()


def resolve_local_now(time_zone_name):
    '''Return (now, configured_zone_str, zone_is_valid).'''
    configured = normalize_time_zone(time_zone_name)
    if configured is None:
        configured = ""
    if not configured:
        return _process_local_now(configured), configured, False
    try:
        now = datetime.now(ZoneInfo(configured))
        return now, configured, True
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        if _is_posix_time_zone(configured):
            try:
                return datetime.now().astimezone(), configured, True
            except (ValueError, OverflowError) as tz_exc:
                _warn_invalid_time_zone(configured, str(tz_exc))
                return _utc_now(), configured, False
        _warn_invalid_time_zone(configured, str(exc))
        return _process_local_now(configured), configured, False


def local_now(time_zone_name):
    '''Current date/time in the configured time zone (IANA or POSIX).'''
    return resolve_local_now(time_zone_name)[0]


def local_today(time_zone_name):
    '''Current calendar date in the configured time zone (IANA or POSIX).'''
    return local_now(time_zone_name).date()


def instance_clock_fields(time_zone_name):
    '''Clock metadata for API responses (today, zone, validity, UTC offset).'''
    now, configured, valid = resolve_local_now(time_zone_name)
    offset = now.utcoffset()
    if offset is None:
        utc_offset_minutes = 0
    else:
        utc_offset_minutes = int(offset.total_seconds() // 60)
    return {
        "today": now.date().isoformat(),
        "time_zone": configured,
        "time_zone_valid": valid,
        "utc_offset_minutes": utc_offset_minutes,
    }


def apply_process_time_zone(time_zone_name):
    '''Apply config time_zone to the process (IANA or POSIX via TZ/tzset).'''
    tz = normalize_time_zone(time_zone_name)
    if not tz:
        return
    os.environ['TZ'] = tz
    time.tzset()


def config_time_zone(config):
    if config is None:
        return None
    return normalize_time_zone(config.config_data.get('time_zone'))
