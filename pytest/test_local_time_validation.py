import time
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import local_time as local_time_mod
from local_time import instance_clock_fields


def test_instance_clock_fields_strips_whitespace():
    manila = ZoneInfo("Asia/Manila")
    fixed = datetime(2026, 10, 9, 8, 30, tzinfo=manila)
    with patch("local_time.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed
        fields = instance_clock_fields(" Asia/Manila ")
    assert fields["time_zone"] == "Asia/Manila"
    assert fields["time_zone_valid"] is True


def test_instance_clock_fields_quoted_posix_valid(
        monkeypatch, restore_process_tz):
    posix = "<+08>-8"
    monkeypatch.setenv("TZ", posix)
    time.tzset()
    local_time_mod._invalid_tz_warned = False
    fields = instance_clock_fields(posix)
    assert fields["time_zone_valid"] is True
    assert fields["utc_offset_minutes"] == 480


def test_instance_clock_fields_est5edt_posix_valid(
        monkeypatch, restore_process_tz):
    posix = "EST5EDT"
    monkeypatch.setenv("TZ", posix)
    time.tzset()
    local_time_mod._invalid_tz_warned = False
    fields = instance_clock_fields(posix)
    assert fields["time_zone_valid"] is True


def test_instance_clock_fields_foo_without_offset_invalid(
        monkeypatch, restore_process_tz):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    local_time_mod._invalid_tz_warned = False
    fields = instance_clock_fields("FOO")
    assert fields["time_zone_valid"] is False


def test_instance_clock_fields_garbage_posix_rule_invalid(
        monkeypatch, restore_process_tz):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    local_time_mod._invalid_tz_warned = False
    fields = instance_clock_fields("CET-1CEST,garbage")
    assert fields["time_zone_valid"] is False


def test_instance_clock_fields_overlong_posix_invalid(
        monkeypatch, restore_process_tz):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    local_time_mod._invalid_tz_warned = False
    overlong = "EST5EDT" + ("X" * 60)
    fields = instance_clock_fields(overlong)
    assert fields["time_zone_valid"] is False


def test_instance_clock_fields_extreme_offset_invalid(
        monkeypatch, restore_process_tz, caplog):
    import logging
    bad = "AAA99"
    monkeypatch.setenv("TZ", bad)
    time.tzset()
    local_time_mod._invalid_tz_warned = False
    caplog.set_level(logging.WARNING)
    fields = instance_clock_fields(bad)
    assert fields["time_zone_valid"] is False
    assert any("Invalid time_zone" in r.message for r in caplog.records)
