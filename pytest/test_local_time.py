from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

from local_time import local_today


def test_local_today_manila_ahead_of_utc_calendar():
    utc = ZoneInfo("UTC")
    instant = datetime(2026, 10, 8, 20, 0, tzinfo=utc)
    with patch("local_time.datetime") as mock_datetime:
        mock_datetime.now.side_effect = (
            lambda tz=None: instant.astimezone(tz or utc))
        assert local_today("Asia/Manila") == datetime(2026, 10, 9).date()
        assert local_today("UTC") == datetime(2026, 10, 8).date()


def test_local_today_us_behind_utc_calendar():
    utc = ZoneInfo("UTC")
    instant = datetime(2026, 10, 9, 3, 0, tzinfo=utc)
    with patch("local_time.datetime") as mock_datetime:
        mock_datetime.now.side_effect = (
            lambda tz=None: instant.astimezone(tz or utc))
        assert local_today("America/Los_Angeles") == datetime(2026, 10, 8).date()
        assert local_today("UTC") == datetime(2026, 10, 9).date()


def test_local_today_invalid_zone_falls_back_to_process_time():
    fixed = datetime(2026, 5, 1, 12, 0, tzinfo=ZoneInfo("UTC"))
    with patch("local_time.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed
        assert local_today("Mars/Olympus") == fixed.date()
