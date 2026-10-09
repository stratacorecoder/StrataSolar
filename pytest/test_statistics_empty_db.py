import json
from pathlib import Path

import server as srv
from config import Config


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


def test_statistics_empty_db_days_count_is_zero(tmp_path, monkeypatch):
    import sqlite3
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    conn = sqlite3.connect(data_dir / "db.sqlite")
    for table in ("days", "months", "years", "all_time"):
        conn.execute(
            f"CREATE TABLE {table} ("
            "date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
            "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    conn.execute(
        "CREATE TABLE highscores ("
        "type TEXT PRIMARY KEY, date TEXT, value REAL)")
    conn.execute(
        "INSERT INTO highscores VALUES ('production', '...', 0.0)")
    conn.commit()
    conn.close()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(srv, "config", Config(_minimal_config_path(tmp_path)))
    stats = json.loads(
        srv.app.test_client().get("/query?type=statistics").data)
    assert stats["days_with_recorded_data"] == 0
    assert stats["average_daily_production_kwh"] == 0.0
