import logging
import os
import re
import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_invalid_tz_warned = False

# POSIX TZ: standard name (3+ letters) with optional numeric offset and DST/rules.
_POSIX_TIME_ZONE = re.compile(
    r"^[A-Za-z]{3,}"
    r"([+-]?\d{1,2}(:[0-5]\d){0,2})?"
    r"([A-Za-z]{3,}([+-]?\d{1,2}(:[0-5]\d){0,2})?)?"
    r"(,.*)?$"
)


def _warn_invalid_time_zone(time_zone_name, exc):
    global _invalid_tz_warned
    if not _invalid_tz_warned:
        logging.warning(
            "Invalid time_zone '%s' (%s); using process local time",
            time_zone_name, exc)
        _invalid_tz_warned = True


def _is_posix_time_zone(time_zone_name):
    if not time_zone_name:
        return False
    # Reject IANA-style Region/City names (POSIX rules may contain '/').
    if re.match(r"^[A-Za-z_+-]+/[A-Za-z_+-]+$", time_zone_name):
        return False
    return _POSIX_TIME_ZONE.match(time_zone_name) is not None


def resolve_local_now(time_zone_name):
    '''Return (now, configured_zone_str, zone_is_valid).'''
    configured = time_zone_name if time_zone_name is not None else ""
    if not time_zone_name:
        return datetime.now().astimezone(), configured, False
    try:
        now = datetime.now(ZoneInfo(time_zone_name))
        return now, configured, True
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        if _is_posix_time_zone(time_zone_name):
            apply_process_time_zone(time_zone_name)
            return datetime.now().astimezone(), configured, True
        _warn_invalid_time_zone(time_zone_name, exc)
        return datetime.now().astimezone(), configured, False


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
    if not time_zone_name:
        return
    os.environ['TZ'] = time_zone_name
    time.tzset()


def config_time_zone(config):
    if config is None:
        return None
    return config.config_data.get('time_zone')
