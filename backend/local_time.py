import logging
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

_invalid_tz_warned = False


def _warn_invalid_time_zone(time_zone_name, exc):
    global _invalid_tz_warned
    if not _invalid_tz_warned:
        logging.warning(
            "Invalid time_zone '%s' (%s); using process local time",
            time_zone_name, exc)
        _invalid_tz_warned = True


def resolve_local_now(time_zone_name):
    '''Return (now, configured_zone_str, zone_is_valid_iana).'''
    configured = time_zone_name if time_zone_name is not None else ""
    if not time_zone_name:
        return datetime.now().astimezone(), configured, False
    try:
        now = datetime.now(ZoneInfo(time_zone_name))
        return now, configured, True
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        _warn_invalid_time_zone(time_zone_name, exc)
        return datetime.now().astimezone(), configured, False


def local_now(time_zone_name):
    '''Current date/time in the configured IANA time zone.'''
    return resolve_local_now(time_zone_name)[0]


def local_today(time_zone_name):
    '''Current calendar date in the configured IANA time zone.'''
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


def config_time_zone(config):
    if config is None:
        return None
    return config.config_data.get('time_zone')
