'''Bataan seasonal daylight uses Manila time and coordinates, not fixed hours.'''

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from solar_curve import default_daylight_hours, distribute_daily_kwh
from solar_time import daylight_active_at, suppress_device_unreachable_at


@pytest.mark.parametrize('month,day,dawn,dusk', [
    (1, 15, (6, 20), (17, 50)),
    (4, 15, (5, 45), (18, 10)),
    (7, 15, (5, 35), (18, 30)),
    (10, 15, (5, 50), (17, 40)),
])
def test_manila_daylight_tracks_bataan_sunrise_sunset(month, day, dawn, dusk):
    zone = ZoneInfo('Asia/Manila')
    for hour, minute in (dawn, dusk):
        when = datetime(2026, month, day, hour, minute, tzinfo=zone)
        # A +5 degree gate deliberately excludes the low-output dawn/dusk.
        assert not daylight_active_at(14.68, 120.54, when, 5)
        assert suppress_device_unreachable_at(14.68, 120.54, when, 5, 60)
    for hour in (9, 12, 15):
        when = datetime(2026, month, day, hour, tzinfo=zone)
        assert daylight_active_at(14.68, 120.54, when, 5)
        assert not suppress_device_unreachable_at(14.68, 120.54, when, 5, 60)
    for hour in (0, 5, 19, 23):
        when = datetime(2026, month, day, hour, tzinfo=zone)
        assert not daylight_active_at(14.68, 120.54, when, 5)


def test_bataan_history_curve_has_no_evening_production():
    assert default_daylight_hours() == (6, 20)
    hourly = distribute_daily_kwh(32)
    assert sum(hourly) == pytest.approx(32)
    assert hourly[:6] == [0] * 6
    assert hourly[20:] == [0] * 4
    assert hourly[13] == max(hourly)
