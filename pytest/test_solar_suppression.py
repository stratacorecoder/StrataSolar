'''High-latitude solar gating for device_unreachable and daylight rules.'''

from datetime import datetime
from zoneinfo import ZoneInfo

from solar_time import (
    daylight_active_at,
    max_solar_elevation_local_day,
    solar_elevation_deg,
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


def test_low_sun_day_suppresses_unreachable_when_sun_never_above_zero():
    tz = ZoneInfo("Europe/Oslo")
    when = datetime(2024, 12, 20, 15, 50, tzinfo=tz)
    assert max_solar_elevation_local_day(*_TROMSO, when) < 0
    assert suppress_device_unreachable_at(*_TROMSO, when, _THRESH, 0)


def test_low_sun_day_allows_unreachable_when_sun_above_zero():
    tz = ZoneInfo("Europe/Oslo")
    when = datetime(2024, 11, 20, 11, 0, tzinfo=tz)
    assert max_solar_elevation_local_day(*_TROMSO, when) < _THRESH
    assert solar_elevation_deg(*_TROMSO, when) > 0
    assert not suppress_device_unreachable_at(*_TROMSO, when, _THRESH, 0)


def test_trondheim_dec_night_suppresses_unreachable():
    tz = ZoneInfo("Europe/Oslo")
    night = datetime(2024, 12, 15, 4, 0, tzinfo=tz)
    assert suppress_device_unreachable_at(*_TRONDHEIM, night, _THRESH, 60)


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
