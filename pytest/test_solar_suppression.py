'''High-latitude solar gating for device_unreachable and daylight rules.'''

from datetime import datetime
from zoneinfo import ZoneInfo

from solar_time import (
    daylight_active_at,
    suppress_device_unreachable_at,
)

_TROMSO = (69.6496, 18.9560)
_TRONDHEIM = (63.4305, 10.3951)
_SVALBARD = (78.2232, 15.6267)
_THRESH = 5.0


def test_tromso_polar_night_allows_alerts_outside_noon_window():
    tz = ZoneInfo("Europe/Oslo")
    night = datetime(2024, 12, 20, 2, 0, tzinfo=tz)
    assert not suppress_device_unreachable_at(
        *_TROMSO, night, _THRESH, 60)
    assert not daylight_active_at(*_TROMSO, night, _THRESH)


def test_tromso_polar_night_suppresses_near_solar_noon():
    tz = ZoneInfo("Europe/Oslo")
    noonish = datetime(2024, 12, 20, 12, 0, tzinfo=tz)
    assert suppress_device_unreachable_at(
        *_TROMSO, noonish, _THRESH, 0)
    assert daylight_active_at(*_TROMSO, noonish, _THRESH)


def test_trondheim_polar_night_allows_overnight_unreachable():
    tz = ZoneInfo("Europe/Oslo")
    night = datetime(2024, 12, 15, 4, 0, tzinfo=tz)
    assert not suppress_device_unreachable_at(
        *_TRONDHEIM, night, _THRESH, 60)


def test_midnight_sun_suppresses_first_hour_after_local_midnight():
    from solar_time import min_solar_elevation_local_day

    tz = ZoneInfo("Europe/Oslo")
    midsummer = datetime(2024, 6, 21, 12, 0, tzinfo=tz)
    assert min_solar_elevation_local_day(*_SVALBARD, midsummer) >= _THRESH
    just_after_midnight = datetime(2024, 6, 21, 0, 30, tzinfo=tz)
    assert suppress_device_unreachable_at(
        *_SVALBARD, just_after_midnight, _THRESH, 0)
    assert not daylight_active_at(
        *_SVALBARD, just_after_midnight, _THRESH)
