import json
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


def _create_export_db(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db_path = data_dir / "db.sqlite"
    conn = sqlite3.connect(db_path)
    conn.execute(
        "CREATE TABLE years ("
        "date INTEGER, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    conn.execute(
        "CREATE TABLE days ("
        "date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    conn.execute(
        "INSERT INTO years VALUES (2026, 0, 10, 0, 5, 0, 2)")
    conn.execute(
        "INSERT INTO days VALUES ('2026-10-08', 0, 3, 0, 2, 0, 1)")
    conn.execute(
        "CREATE TABLE real_time ("
        "ID INTEGER PRIMARY KEY, col1 REAL, col2 REAL, col3 REAL, "
        "col4 REAL, col5 REAL, col6 REAL)")
    conn.commit()
    conn.close()


def test_name_endpoint_returns_configured_name(tmp_path, monkeypatch):
    monkeypatch.setattr(
        srv, "config", Config(_minimal_config_path(tmp_path)))
    client = srv.app.test_client()
    response = client.get("/name")
    assert response.status_code == 200
    assert json.loads(response.data) == "API Site"


def test_csv_years_table_without_date_filter(tmp_path, monkeypatch):
    _create_export_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    client = srv.app.test_client()
    response = client.get("/csv?table=years")
    assert response.status_code == 200
    body = response.data.decode("utf-8")
    assert body.startswith("date;production;consumption;feed_in\n2026;")
    assert response.headers["Content-Disposition"] == (
        'attachment; filename="1Bataan_All.csv"')


def test_csv_days_with_date_filter(tmp_path, monkeypatch):
    _create_export_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    client = srv.app.test_client()
    response = client.get("/csv?table=days&date=2026-10-08")
    assert response.status_code == 200
    assert "2026-10-08;" in response.data.decode("utf-8")
    assert response.headers["Content-Disposition"] == (
        'attachment; filename="1Bataan_2026-10-08.csv"')


def test_csv_rejects_invalid_table(tmp_path, monkeypatch):
    _create_export_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    client = srv.app.test_client()
    response = client.get("/csv?table=sqlite_master")
    assert response.status_code == 400
    assert json.loads(response.data) == {"state": "error"}


def test_csv_rejects_sql_injection_in_date(tmp_path, monkeypatch):
    _create_export_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    client = srv.app.test_client()
    response = client.get("/csv?table=days&date=2026' OR '1'='1")
    assert response.status_code == 400


def test_query_historical_rejects_invalid_table(tmp_path, monkeypatch):
    _create_export_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        srv, "config", Config(_minimal_config_path(tmp_path)))
    client = srv.app.test_client()
    response = client.get(
        "/query?type=historical&table=days;DROP&date=2026-10-08")
    assert response.status_code == 400


def test_query_real_time_rejects_invalid_hours(tmp_path, monkeypatch):
    _create_export_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    client = srv.app.test_client()
    response = client.get("/query?type=real_time&h=1;DROP TABLE real_time")
    assert response.status_code == 400


def test_csv_rejects_date_with_trailing_newline(tmp_path, monkeypatch):
    _create_export_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    client = srv.app.test_client()
    response = client.get("/csv?table=days&date=2026%0A")
    assert response.status_code == 400


def test_query_missing_type_returns_400(tmp_path, monkeypatch, caplog):
    _create_export_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    import logging
    with caplog.at_level(logging.ERROR):
        client = srv.app.test_client()
        response = client.get("/query")
    assert response.status_code == 400
    assert json.loads(response.data) == {"state": "error"}
    assert not caplog.records


def test_query_unknown_type_returns_400(tmp_path, monkeypatch, caplog):
    _create_export_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    import logging
    with caplog.at_level(logging.ERROR):
        client = srv.app.test_client()
        response = client.get("/query?type=bogus")
    assert response.status_code == 400
    assert not caplog.records


def test_query_historical_missing_date_returns_400(tmp_path, monkeypatch):
    _create_export_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        srv, "config", Config(_minimal_config_path(tmp_path)))
    client = srv.app.test_client()
    response = client.get("/query?type=historical&table=days")
    assert response.status_code == 400


def test_query_real_time_rejects_overlong_hours(tmp_path, monkeypatch, caplog):
    _create_export_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    import logging
    with caplog.at_level(logging.ERROR):
        client = srv.app.test_client()
        response = client.get("/query?type=real_time&h=" + ("9" * 5000))
    assert response.status_code == 400
    assert json.loads(response.data) == {"state": "error"}
    assert not caplog.records


def test_query_real_time_zero_hours_returns_empty_list(tmp_path, monkeypatch):
    _create_export_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    client = srv.app.test_client()
    response = client.get("/query?type=real_time&h=0")
    assert response.status_code == 200
    assert json.loads(response.data) == []
