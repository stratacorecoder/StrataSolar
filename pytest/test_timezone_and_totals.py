import json
import sqlite3
from datetime import date
from pathlib import Path
from unittest.mock import patch

import server as srv
from config import Config
from grabber import insert_historical_values
from database import Database


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
    assert stats["average_daily_production_kwh"] == 101.0 / 1


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
