'''High-latitude solar gating for device_unreachable and daylight rules.'''

from datetime import datetime
from zoneinfo import ZoneInfo

from solar_time import (
    daylight_active_at,
    max_solar_elevation_local_day,
    suppress_device_unreachable_at,
)

_TROMSO = (69.6496, 18.9560)
_TRONDHEIM = (63.4305, 10.3951)
_SVALBARD = (78.2232, 15.6267)
_THRESH = 5.0


def test_tromso_polar_night_no_daylight_any_time():
    tz = ZoneInfo("Europe/Oslo")
    for hour in (2, 10, 12, 15):
        when = datetime(2024, 12, 20, hour, 0, tzinfo=tz)
        assert max_solar_elevation_local_day(*_TROMSO, when) < _THRESH
        assert not daylight_active_at(*_TROMSO, when, _THRESH)


def test_tromso_polar_night_unreachable_not_suppressed_at_noon_window():
    tz = ZoneInfo("Europe/Oslo")
    morning_outage = datetime(2024, 12, 20, 10, 0, tzinfo=tz)
    assert not suppress_device_unreachable_at(
        *_TROMSO, morning_outage, _THRESH, 60)


def test_tromso_polar_night_unreachable_suppressed_late_afternoon():
    tz = ZoneInfo("Europe/Oslo")
    afternoon = datetime(2024, 12, 20, 15, 50, tzinfo=tz)
    assert suppress_device_unreachable_at(
        *_TROMSO, afternoon, _THRESH, 0)


def test_trondheim_polar_night_suppresses_deep_night():
    tz = ZoneInfo("Europe/Oslo")
    night = datetime(2024, 12, 15, 4, 0, tzinfo=tz)
    assert suppress_device_unreachable_at(
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
