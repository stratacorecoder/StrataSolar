import json
import os
import sqlite3
from pathlib import Path

import server as srv
from config import Config


def _minimal_config_path(tmp_path: Path, extra: str = "") -> str:
    text = """
logging: normal
time_zone: Europe/Berlin
device:
  type: Dummy
  start_date: 2020-01-01
prices:
  price_per_grid_kwh: 0.1
  revenue_per_fed_in_kwh: 0.1
server:
  ip: 0.0.0.0
  port: 5000
grabber:
  interval_s: 5
stratasolar:
  name: "API Site"
""" + extra
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def test_name_endpoint_returns_configured_name(tmp_path, monkeypatch):
    monkeypatch.setattr(
        srv, "config", Config(_minimal_config_path(tmp_path)))
    client = srv.app.test_client()
    response = client.get("/name")
    assert response.status_code == 200
    assert json.loads(response.data) == "API Site"


def test_csv_years_table_without_date_filter(tmp_path, monkeypatch):
    db_path = tmp_path / "db.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE years ("
        "date INTEGER, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    conn.execute(
        "INSERT INTO years VALUES (2026, 0, 10, 0, 5, 0, 2)")
    conn.commit()
    conn.close()

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "db.sqlite").write_bytes(db_path.read_bytes())

    original_cwd = Path.cwd()
    try:
        os.chdir(tmp_path)
        client = srv.app.test_client()
        response = client.get("/csv?table=years")
        assert response.status_code == 200
        body = response.data.decode("utf-8")
        assert body.startswith("date;production;consumption;feed_in\n2026;")
        assert response.headers["Content-Disposition"] == (
            'attachment; filename="StrataSolar_All.csv"')
    finally:
        os.chdir(original_cwd)
