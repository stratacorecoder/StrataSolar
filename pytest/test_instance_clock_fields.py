import json
import time
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import server as srv
from config import Config
from local_time import instance_clock_fields


def _minimal_config_path(tmp_path: Path, time_zone: str) -> str:
    text = f"""
logging: normal
time_zone: "{time_zone}"
device:
  type: Dummy
  start_date: 2020-08-01
prices:
  price_per_grid_kwh: 0.1
  revenue_per_fed_in_kwh: 0.1
server:
  ip: 0.0.0.0
  port: 5000
grabber:
  interval_s: 5
"""
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_instance_clock_fields_valid_iana_zone():
    manila = ZoneInfo("Asia/Manila")
    fixed = datetime(2026, 10, 9, 8, 30, tzinfo=manila)
    with patch("local_time.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed
        fields = instance_clock_fields("Asia/Manila")
    assert fields == {
        "today": "2026-10-09",
        "time_zone": "Asia/Manila",
        "time_zone_valid": True,
        "utc_offset_minutes": 480,
    }


def test_instance_clock_fields_invalid_zone_falls_back(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    fixed = datetime(2026, 10, 8, 23, 0, tzinfo=timezone.utc)
    with patch("local_time.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed
        fields = instance_clock_fields("Mars/Olympus")
    assert fields["today"] == fixed.astimezone().date().isoformat()
    assert fields["time_zone"] == "Mars/Olympus"
    assert fields["time_zone_valid"] is False
    assert fields["utc_offset_minutes"] == 0


def test_dates_endpoint_includes_clock_fields(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    import sqlite3
    conn = sqlite3.connect(data_dir / "db.sqlite")
    conn.execute(
        "CREATE TABLE years ("
        "date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    conn.execute("INSERT INTO years VALUES ('2024', 0, 1, 0, 1, 0, 1)")
    conn.commit()
    conn.close()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        srv, "config", Config(_minimal_config_path(tmp_path, "Asia/Manila")))
    with patch("server.instance_clock_fields", return_value={
        "today": "2026-10-09",
        "time_zone": "Asia/Manila",
        "time_zone_valid": True,
        "utc_offset_minutes": 480,
    }):
        payload = json.loads(
            srv.app.test_client().get("/query?type=dates").data)
    assert payload["today"] == "2026-10-09"
    assert payload["time_zone_valid"] is True


def test_current_endpoint_includes_clock_fields_on_fallback(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    import sqlite3
    conn = sqlite3.connect(data_dir / "db.sqlite")
    for table in ("days", "months", "years", "all_time"):
        conn.execute(
            f"CREATE TABLE {table} ("
            "date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
            "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    conn.execute(
        "CREATE TABLE current ("
        "date TEXT PRIMARY KEY, produced REAL, consumed_grid REAL, "
        "consumed_pv REAL, consumed_total REAL, fed_in REAL)")
    conn.execute(
        "INSERT INTO current VALUES ('cur', 0, 0, 0, 0, 0)")
    conn.execute(
        "INSERT INTO all_time VALUES ('all_time', 0, 0, 0, 0, 0, 0)")
    conn.commit()
    conn.close()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        srv, "config", Config(_minimal_config_path(tmp_path, "Mars/Olympus")))
    with patch("server.local_today", return_value=date(2026, 10, 8)):
        with patch("server.instance_clock_fields", return_value={
            "today": "2026-10-08",
            "time_zone": "Mars/Olympus",
            "time_zone_valid": False,
            "utc_offset_minutes": 0,
        }):
            payload = json.loads(
                srv.app.test_client().get("/query?type=current").data)
    assert payload["time_zone"] == "Mars/Olympus"
    assert payload["time_zone_valid"] is False
    assert payload["today"] == "2026-10-08"
