import os
import time

import local_time as local_time_mod
from local_time import (
    configure_process_time_zone_at_startup,
    instance_clock_fields,
)


def test_invalid_garbage_posix_rule_sets_process_utc(
        monkeypatch, restore_process_tz):
    bad = "CET-1CEST,garbage"
    local_time_mod._invalid_tz_warned = False
    configure_process_time_zone_at_startup(bad)
    assert os.environ.get("TZ") == "UTC"
    fields = instance_clock_fields(bad)
    assert fields["time_zone_valid"] is False
    assert fields["utc_offset_minutes"] == 0


def test_invalid_broken_dst_rule_sets_process_utc(
        monkeypatch, restore_process_tz):
    bad = "EST5EDT,M99.9.9"
    local_time_mod._invalid_tz_warned = False
    configure_process_time_zone_at_startup(bad)
    assert os.environ.get("TZ") == "UTC"
    fields = instance_clock_fields(bad)
    assert fields["time_zone_valid"] is False
    assert fields["utc_offset_minutes"] == 0


def test_valid_posix_keeps_configured_process_tz(
        monkeypatch, restore_process_tz):
    posix = "CET-1CEST,M3.5.0,M10.5.0/3"
    configure_process_time_zone_at_startup(posix)
    assert os.environ.get("TZ") == posix
    time.tzset()
    fields = instance_clock_fields(posix)
    assert fields["time_zone_valid"] is True
