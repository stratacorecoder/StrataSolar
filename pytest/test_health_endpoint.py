import json
from pathlib import Path

import server as srv
from aggregates import touch_grabber_loop_heartbeat
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
  interval_s: 10
"""
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _seed_db(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db = Database(str(data_dir / "db.sqlite"))
    db.execute(
        "CREATE TABLE current ("
        "date TEXT PRIMARY KEY, produced REAL, consumed_grid REAL, "
        "consumed_pv REAL, consumed_total REAL, fed_in REAL)")
    db.execute("INSERT INTO current VALUES ('cur', 0, 0, 0, 0, 0)")
    touch_grabber_loop_heartbeat(db)
    db.close()


def test_health_ok_when_grabber_fresh(tmp_path, monkeypatch):
    _seed_db(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        srv, "config", Config(_minimal_config_path(tmp_path)))
    response = srv.app.test_client().get("/health")
    assert response.status_code == 200
    assert json.loads(response.data)["state"] == "ok"


def test_health_degraded_when_grabber_stale(tmp_path, monkeypatch):
    _seed_db(tmp_path)
    db = Database(str(tmp_path / "data" / "db.sqlite"))
    db.execute(
        "CREATE TABLE IF NOT EXISTS schema_meta "
        "(key TEXT PRIMARY KEY, value TEXT)")
    db.execute_params_no_result(
        "INSERT OR REPLACE INTO schema_meta (key, value) VALUES (?, ?)",
        ("grabber_last_loop_utc", "2020-01-01T00:00:00+00:00"))
    db.close()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        srv, "config", Config(_minimal_config_path(tmp_path)))
    response = srv.app.test_client().get("/health")
    assert response.status_code == 503
    assert json.loads(response.data)["state"] == "degraded"
