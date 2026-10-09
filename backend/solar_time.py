'''Approximate solar elevation for daylight gating (no network).'''

import math
from datetime import timezone


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


def minutes_since_elevation_reached(latitude, longitude, when, threshold_deg):
    '''Minutes since sun first rose above threshold_deg on this local day.'''
    from datetime import timedelta

    if solar_elevation_deg(latitude, longitude, when) < threshold_deg:
        return None
    day_start = when.replace(hour=0, minute=0, second=0, microsecond=0)
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
