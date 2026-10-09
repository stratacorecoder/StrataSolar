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


def local_now(time_zone_name):
    '''Current date/time in the configured IANA time zone.'''
    if not time_zone_name:
        return datetime.now().astimezone()
    try:
        return datetime.now(ZoneInfo(time_zone_name))
    except (ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        _warn_invalid_time_zone(time_zone_name, exc)
        return datetime.now().astimezone()


def local_today(time_zone_name):
    '''Current calendar date in the configured IANA time zone.'''
    return local_now(time_zone_name).date()


def config_time_zone(config):
    if config is None:
        return None
    return config.config_data.get('time_zone')
