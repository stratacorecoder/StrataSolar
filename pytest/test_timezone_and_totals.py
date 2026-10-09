import json
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import server as srv
from config import Config
from aggregates import migrate_legacy_all_time_baseline
import local_time as local_time_mod
from local_time import apply_process_time_zone, local_today
from grabber import insert_historical_values, update_data
from database import Database
from devices.Dummy import Dummy


def _minimal_config_path(tmp_path: Path, time_zone: str = "Asia/Manila") -> str:
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
stratasolar:
  name: "Test"
"""
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _seed_history_db(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "db.sqlite"
    conn = sqlite3.connect(db_path)
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
        "INSERT INTO current VALUES ('cur', 1.0, 0.0, 0.5, 0.5, 0.2)")
    conn.execute(
        "INSERT INTO days VALUES ('2026-10-09', 100, 110, 50, 55, 20, 22)")
    conn.execute(
        "INSERT INTO years VALUES ('2026', 0, 101, 0, 80, 0, 40)")
    conn.execute(
        "INSERT INTO all_time VALUES ('all_time', 0, 543, 0, 400, 0, 200)")
    conn.execute(
        "CREATE TABLE highscores ("
        "type TEXT PRIMARY KEY, date TEXT, value REAL)")
    conn.execute(
        "INSERT INTO highscores VALUES ('production', '2026-10-09', 3.0)")
    conn.commit()
    conn.close()


def test_current_uses_local_calendar_day_not_missing_utc_day(
        tmp_path, monkeypatch):
    _seed_history_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        srv, "config", Config(_minimal_config_path(tmp_path)))
    client = srv.app.test_client()
    with patch("server.local_today", return_value=date(2026, 10, 9)):
        response = client.get("/query?type=current")
    assert response.status_code == 200
    data = json.loads(response.data)
    assert data["state"] == "ok"
    assert data["today_produced_kwh"] == 10.0
    assert data["all_time_produced_kwh"] == 101.0


def test_current_missing_today_row_returns_zeros(tmp_path, monkeypatch):
    _seed_history_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        srv, "config", Config(_minimal_config_path(tmp_path)))
    client = srv.app.test_client()
    with patch("server.local_today", return_value=date(2026, 10, 8)):
        data = json.loads(client.get("/query?type=current").data)
    assert data["state"] == "ok"
    assert data["today_produced_kwh"] == 0.0
    assert data["all_time_produced_kwh"] == 101.0


def test_all_time_totals_match_sum_of_year_rows(tmp_path, monkeypatch):
    _seed_history_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        srv, "config", Config(_minimal_config_path(tmp_path)))
    current = json.loads(
        srv.app.test_client().get("/query?type=current").data)
    years_detail = json.loads(
        srv.app.test_client().get("/query?type=years_in_all_time").data)
    year_total = sum(entry["produced_self"] + entry["produced_feed_in"]
                     for entry in years_detail)
    assert current["all_time_produced_kwh"] == year_total


def test_statistics_average_uses_recorded_history(tmp_path, monkeypatch):
    _seed_history_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        srv, "config", Config(_minimal_config_path(tmp_path)))
    with patch("server.local_today", return_value=date(2026, 10, 9)):
        stats = json.loads(
            srv.app.test_client().get("/query?type=statistics").data)
    assert stats["history_first_recorded_date"] == "2026-10-09"
    assert stats["days_with_recorded_data"] == 1
    assert stats["average_daily_production_kwh"] == 10.0


def _seed_legacy_main_format_db(tmp_path: Path) -> None:
    """DB shape from main: all_time._a = 0, _b = device lifetime counters."""
    data_dir = tmp_path / "data"
    data_dir.mkdir()
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
        "INSERT INTO current VALUES ('cur', 1.0, 0.0, 0.5, 0.5, 0.2)")
    conn.execute(
        "INSERT INTO years VALUES ('2024', 12000, 20456, 12000, 32708, "
        "12000, 13182)")
    conn.execute(
        "INSERT INTO all_time VALUES ('all_time', 0, 32456, 0, 52708, "
        "0, 13182)")
    conn.execute(
        "CREATE TABLE highscores ("
        "type TEXT PRIMARY KEY, date TEXT, value REAL)")
    conn.execute(
        "INSERT INTO highscores VALUES ('production', '2024-01-01', 3.0)")
    conn.commit()
    conn.close()


def test_upgraded_db_all_time_matches_history_and_dashboard(tmp_path, monkeypatch):
    _seed_legacy_main_format_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        srv, "config", Config(_minimal_config_path(tmp_path)))
    client = srv.app.test_client()
    current = json.loads(client.get("/query?type=current").data)
    history = json.loads(
        client.get("/query?type=historical&table=all_time&date=all_time").data)
    assert current["all_time_produced_kwh"] == 8456.0
    assert history["produced_kwh"] == 8456.0
    assert current["device_lifetime_produced_kwh"] == 32456.0


def test_migrate_legacy_all_time_is_idempotent(tmp_path):
    _seed_legacy_main_format_db(tmp_path)
    db_path = tmp_path / "data" / "db.sqlite"
    db = Database(str(db_path))
    produced_b_before = db.execute("SELECT produced_b FROM all_time")[0][0]
    assert migrate_legacy_all_time_baseline(db) is True
    row1 = db.execute("SELECT * FROM all_time")[0]
    assert migrate_legacy_all_time_baseline(db) is False
    row2 = db.execute("SELECT * FROM all_time")[0]
    assert row1 == row2
    assert row1[2] == produced_b_before
    assert row1[2] - row1[1] == 8456.0


def test_migrate_runs_once_when_b_equals_year_sum(tmp_path):
    db_path = tmp_path / "db.sqlite"
    db = Database(str(db_path))
    db.execute(
        "CREATE TABLE years ("
        "date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    db.execute(
        "CREATE TABLE all_time ("
        "date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    db.execute("INSERT INTO years VALUES ('2026', 0, 100, 0, 50, 0, 25)")
    db.execute(
        "INSERT INTO all_time VALUES ('all_time', 0, 100, 0, 50, 0, 25)")
    assert migrate_legacy_all_time_baseline(db) is True
    assert migrate_legacy_all_time_baseline(db) is False
    row = db.execute("SELECT * FROM all_time")[0]
    assert row[1] == 0
    assert row[2] == 100


def test_readonly_unmigrated_db_serves_current(tmp_path, monkeypatch):
    _seed_legacy_main_format_db(tmp_path)
    db_path = tmp_path / "data" / "db.sqlite"
    import os
    os.chmod(db_path, 0o444)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        srv, "config", Config(_minimal_config_path(tmp_path)))
    payload = json.loads(
        srv.app.test_client().get("/query?type=current").data)
    assert payload["state"] == "ok"
    assert payload["all_time_produced_kwh"] == 8456.0
    os.chmod(db_path, 0o644)


def test_server_posix_time_zone_matches_grabber_day(
        monkeypatch, restore_process_tz):
    apply_process_time_zone("CET-1CEST,M3.5.0,M10.5.0/3")
    fixed = datetime(2026, 12, 31, 23, 30, tzinfo=timezone.utc)
    with patch("local_time.datetime") as mock_datetime:
        mock_datetime.now.return_value = fixed
        today = local_today("CET-1CEST,M3.5.0,M10.5.0/3")
    assert today.isoformat() == "2027-01-01"


def test_grabber_continues_with_invalid_time_zone(tmp_path, monkeypatch):
    local_time_mod._invalid_tz_warned = False
    from grabber import create_new_db
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    cfg = Config(_minimal_config_path(tmp_path, time_zone="Mars/Olympus"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("grabber.config", cfg)
    create_new_db()
    device = Dummy(cfg)
    update_data(device)
    db = Database("data/db.sqlite")
    assert db.execute("SELECT COUNT(*) FROM days")[0][0] == 1


def test_grabber_records_with_extreme_posix_offset(
        tmp_path, monkeypatch, restore_process_tz):
    local_time_mod._invalid_tz_warned = False
    from grabber import create_new_db
    apply_process_time_zone("AAA99")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    cfg = Config(_minimal_config_path(tmp_path, time_zone="AAA99"))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr("grabber.config", cfg)
    create_new_db()
    device = Dummy(cfg)
    update_data(device)
    db = Database("data/db.sqlite")
    assert db.execute("SELECT COUNT(*) FROM days")[0][0] == 1


def test_grabber_baselines_all_time_counters(tmp_path):
    db_path = tmp_path / "db.sqlite"
    db = Database(str(db_path))
    db.execute(
        "CREATE TABLE all_time ("
        "date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    db.execute(
        "INSERT INTO all_time VALUES ('all_time', 0, 0, 0, 0, 0, 0)")
    insert_historical_values(db, "all_time", "all_time", 440.0, 390.0, 240.0)
    insert_historical_values(db, "all_time", "all_time", 441.0, 391.0, 241.0)
    rows = db.execute("SELECT * FROM all_time")
    assert rows[0][1] == 440.0
    assert rows[0][2] == 441.0
    assert rows[0][2] - rows[0][1] == 1.0
