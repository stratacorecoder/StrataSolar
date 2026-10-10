'''Normalized intraday solar production shape (local hours).'''

import math


def default_daylight_hours():
    # Approximate Bataan daylight for the history-only fallback. Equipment
    # alerts use the coordinate-based sun elevation, not these fixed hours.
    return 6, 18


def hour_weight(hour, start_hour, end_hour):
    if hour < start_hour or hour >= end_hour:
        return 0.0
    span = end_hour - start_hour
    if span <= 0:
        return 0.0
    x = (hour - start_hour) / span
    return math.sin(math.pi * x)


def distribute_daily_kwh(daily_kwh, start_hour=6, end_hour=18):
    '''Return list of 24 hourly kWh values summing to daily_kwh.'''
    weights = [hour_weight(h, start_hour, end_hour) for h in range(24)]
    total = sum(weights)
    if total <= 0 or daily_kwh <= 0:
        return [0.0] * 24
    scale = daily_kwh / total
    return [w * scale for w in weights]


def cumulative_hourly(hourly):
    running = 0.0
    out = []
    for v in hourly:
        running += v
        out.append(running)
    return out
