import json
from pathlib import Path

import server as srv
from aggregates import sum_years_deltas
from config import Config
from database import Database


def _minimal_config_path(tmp_path: Path) -> str:
    text = """
logging: normal
time_zone: "UTC"
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


def _seed_negative_year_db(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db = Database(str(data_dir / "db.sqlite"))
    for table in ("days", "months", "years", "all_time"):
        db.execute(
            f"CREATE TABLE {table} ("
            "date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
            "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    db.execute(
        "INSERT INTO years VALUES ('2026', 1000, 12, 0, 0, 0, 0)")
    db.execute(
        "INSERT INTO days VALUES ('2026-10-09', 1000, 12, 0, 0, 0, 0)")
    db.execute(
        "CREATE TABLE current ("
        "date TEXT PRIMARY KEY, produced REAL, consumed_grid REAL, "
        "consumed_pv REAL, consumed_total REAL, fed_in REAL)")
    db.execute(
        "INSERT INTO current VALUES ('cur', 0, 0, 0, 0, 0)")
    db.execute(
        "CREATE TABLE highscores (type TEXT PRIMARY KEY, date TEXT, value REAL)")
    db.execute("INSERT INTO highscores VALUES ('production', 'x', 0)")
    db.execute(
        "CREATE TABLE schema_meta (key TEXT PRIMARY KEY, value TEXT)")
    db.execute(
        "INSERT INTO schema_meta VALUES ('grabber_last_sample_utc', "
        "'2026-10-09T12:00:00+00:00')")


def test_sum_years_clamps_negative_row(tmp_path):
    _seed_negative_year_db(tmp_path)
    db = Database(str(tmp_path / "data" / "db.sqlite"))
    assert sum_years_deltas(db)[0] == 0.0


def test_current_and_history_clamp_negative_rows(tmp_path, monkeypatch):
    _seed_negative_year_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        srv, "config", Config(_minimal_config_path(tmp_path)))
    client = srv.app.test_client()
    current = json.loads(client.get("/query?type=current").data)
    assert current["all_time_produced_kwh"] == 0.0
    csv = client.get("/csv?table=days&date=2026-10").data.decode()
    assert ";-88.0;" not in csv
    assert ";0.0;" in csv
    stats = json.loads(client.get("/query?type=statistics").data)
    assert stats["average_daily_production_kwh"] == 0.0
    assert stats["best_day_production_kwh"] == 0.0
