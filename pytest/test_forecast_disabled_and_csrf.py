import json

import server as srv
from config import Config
from database import Database
from db_migrate import ensure_feature_schema
from forecast_service import persist_forecast_cache


def _minimal_config(tmp_path, extra=""):
    text = """
logging: normal
time_zone: UTC
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
""" + extra
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return Config(str(path))


def test_forecast_disabled_ignores_stale_cache(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db = Database(str(data_dir / "db.sqlite"))
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    persist_forecast_cache(db, {
        "state": "ok",
        "source": "open_meteo",
        "generated_at": "2026-10-09T00:00:00+00:00",
        "today": "2026-10-09",
        "days": [],
    })
    db.close()
    monkeypatch.chdir(tmp_path)
    cfg = _minimal_config(tmp_path, "forecast:\n  enabled: false\n")
    monkeypatch.setattr(srv, "config", cfg)
    resp = srv.app.test_client().get("/query?type=forecast")
    data = json.loads(resp.data)
    assert data["state"] == "disabled"


def test_acknowledge_rejects_non_json(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db = Database(str(data_dir / "db.sqlite"))
    ensure_feature_schema(db)
    db.execute_params_no_result(
        "INSERT INTO alerts (rule_id, severity, title, message, started_at, status) "
        "VALUES ('test', 'info', 'T', 'M', '2026-01-01T00:00:00+00:00', 'open')")
    db.close()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(srv, "config", _minimal_config(tmp_path))
    client = srv.app.test_client()
    resp = client.post("/alerts/acknowledge?id=1", data="{}", content_type="text/plain")
    assert resp.status_code == 415


def test_alerts_list_returns_open_separately(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db = Database(str(data_dir / "db.sqlite"))
    ensure_feature_schema(db)
    for i in range(3):
        db.execute_params_no_result(
            "INSERT INTO alerts (rule_id, severity, title, message, started_at, status) "
            "VALUES ('test', 'info', 'T', 'M', ?, 'open')",
            (f"2026-01-0{i}T00:00:00+00:00",))
    for i in range(5):
        db.execute_params_no_result(
            "INSERT INTO alerts (rule_id, severity, title, message, started_at, "
            "ended_at, status) VALUES ('test', 'info', 'T', 'M', ?, ?, 'resolved')",
            (f"2025-12-0{i}T00:00:00+00:00", f"2025-12-0{i}T01:00:00+00:00"))
    db.close()
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(srv, "config", _minimal_config(tmp_path))
    data = json.loads(
        srv.app.test_client().get("/query?type=alerts&status=list").data)
    assert len(data["open_alerts"]) == 3
    assert data["open_count"] == 3
