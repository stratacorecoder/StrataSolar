'''Approximate solar elevation for daylight gating (no network).'''

import math
from datetime import timedelta, timezone


def _to_utc(dt):
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def solar_elevation_deg(latitude, longitude, when):
    '''Return sun elevation in degrees at the given local/aware datetime.'''
    when_utc = _to_utc(when)
    day = when_utc.timetuple().tm_yday
    hour = (
        when_utc.hour + when_utc.minute / 60.0
        + when_utc.second / 3600.0)
    gamma = 2 * math.pi / 365 * (day - 1 + (hour - 12) / 24)
    decl = (
        0.006918
        - 0.399912 * math.cos(gamma)
        + 0.070257 * math.sin(gamma)
        - 0.006758 * math.cos(2 * gamma)
        + 0.000907 * math.sin(2 * gamma)
        - 0.002697 * math.cos(3 * gamma)
        + 0.00148 * math.sin(3 * gamma))
    eqtime = 229.18 * (
        0.000075
        + 0.001868 * math.cos(gamma)
        - 0.032077 * math.sin(gamma)
        - 0.014615 * math.cos(2 * gamma)
        - 0.040849 * math.sin(2 * gamma))
    time_offset = eqtime + 4 * longitude
    tst = hour * 60 + time_offset
    ha = math.radians((tst / 4) - 180)
    lat_r = math.radians(latitude)
    zenith = math.acos(
        math.sin(lat_r) * math.sin(decl)
        + math.cos(lat_r) * math.cos(decl) * math.cos(ha))
    return 90 - math.degrees(zenith)


def _local_day_start(when):
    return when.replace(hour=0, minute=0, second=0, microsecond=0)


def _sample_elevations_local_day(latitude, longitude, when_local, step_minutes=30):
    day_start = _local_day_start(when_local)
    end = day_start + timedelta(days=1)
    t = day_start
    while t < end:
        yield solar_elevation_deg(latitude, longitude, t)
        t += timedelta(minutes=step_minutes)


def max_solar_elevation_local_day(latitude, longitude, when_local):
    return max(_sample_elevations_local_day(latitude, longitude, when_local))


def min_solar_elevation_local_day(latitude, longitude, when_local):
    return min(_sample_elevations_local_day(latitude, longitude, when_local))


def solar_noon_hour_local(latitude, longitude, when_local):
    '''Approximate local solar noon as fractional hour on this calendar day.'''
    day_start = _local_day_start(when_local)
    best_h = 12.0
    best_e = -90.0
    for minutes in range(0, 24 * 60, 15):
        t = day_start + timedelta(minutes=minutes)
        elev = solar_elevation_deg(latitude, longitude, t)
        if elev > best_e:
            best_e = elev
            best_h = minutes / 60.0
    return best_h


def _hours_from_solar_noon(when_local, noon_hour):
    h = when_local.hour + when_local.minute / 60.0 + when_local.second / 3600.0
    return abs((h - noon_hour + 12) % 24 - 12)


_POLAR_NOON_WINDOW_H = 4.0
_MIDNIGHT_SUN_SUPPRESS_MIN = 60


def minutes_since_elevation_reached(latitude, longitude, when, threshold_deg):
    '''Minutes since sun first rose above threshold_deg on this local day.'''
    if solar_elevation_deg(latitude, longitude, when) < threshold_deg:
        return None
    day_start = _local_day_start(when)
    step = timedelta(minutes=5)
    t = day_start
    first_above = None
    while t <= when:
        if solar_elevation_deg(latitude, longitude, t) >= threshold_deg:
            first_above = t
            break
        t += step
    if first_above is None:
        return 0.0
    return (when - first_above).total_seconds() / 60.0


def daylight_active_at(latitude, longitude, when_local, threshold_deg):
    '''Whether alert "daylight" rules should treat this moment as daytime.'''
    max_e = max_solar_elevation_local_day(latitude, longitude, when_local)
    if max_e < threshold_deg:
        return False
    min_e = min_solar_elevation_local_day(latitude, longitude, when_local)
    if min_e >= threshold_deg:
        mins = when_local.hour * 60 + when_local.minute
        return mins >= _MIDNIGHT_SUN_SUPPRESS_MIN
    return solar_elevation_deg(latitude, longitude, when_local) >= threshold_deg


def suppress_device_unreachable_at(
        latitude, longitude, when_local, threshold_deg, grace_minutes):
    '''Whether to suppress opening a new device_unreachable alert.'''
    max_e = max_solar_elevation_local_day(latitude, longitude, when_local)
    if max_e < threshold_deg:
        noon = solar_noon_hour_local(latitude, longitude, when_local)
        if _hours_from_solar_noon(when_local, noon) <= _POLAR_NOON_WINDOW_H:
            return False
        return solar_elevation_deg(
            latitude, longitude, when_local) < threshold_deg
    min_e = min_solar_elevation_local_day(latitude, longitude, when_local)
    if min_e >= threshold_deg:
        mins = when_local.hour * 60 + when_local.minute
        return mins < _MIDNIGHT_SUN_SUPPRESS_MIN
    elev = solar_elevation_deg(latitude, longitude, when_local)
    if elev < threshold_deg:
        return True
    if grace_minutes > 0:
        mins = minutes_since_elevation_reached(
            latitude, longitude, when_local, threshold_deg)
        if mins is not None and mins < grace_minutes:
            return True
    return False
