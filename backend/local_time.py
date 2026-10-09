from datetime import date, datetime
from zoneinfo import ZoneInfo


def local_now(time_zone_name):
    '''Current date/time in the configured IANA time zone.'''
    if not time_zone_name:
        return datetime.now().astimezone()
    return datetime.now(ZoneInfo(time_zone_name))


def local_today(time_zone_name):
    '''Current calendar date in the configured IANA time zone.'''
    return local_now(time_zone_name).date()


def config_time_zone(config):
    if config is None:
        return None
    return config.config_data.get('time_zone')
