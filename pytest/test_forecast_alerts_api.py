import json
from datetime import datetime, timezone

import server as srv
from config import Config
from database import Database
from db_migrate import ensure_feature_schema
from forecast_service import persist_forecast_cache
from local_time import local_today


def _minimal_config_path(tmp_path):
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
"""
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return str(path)


def _seed(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    db = Database(str(data_dir / "db.sqlite"))
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    today = local_today("UTC").isoformat()
    persist_forecast_cache(db, {
        "state": "ok",
        "source": "history",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "today": today,
        "today_forecast_kwh": 10,
        "days": [{"date": today, "production_kwh": 10, "consumption_kwh": 1}],
    })
    db.close()


def test_forecast_query_endpoint(tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(srv, "config", Config(_minimal_config_path(tmp_path)))
    client = srv.app.test_client()
    resp = client.get("/query?type=forecast")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["state"] == "ok"
    assert "accuracy_recent" in data


def test_alerts_query_endpoint(tmp_path, monkeypatch):
    _seed(tmp_path)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(srv, "config", Config(_minimal_config_path(tmp_path)))
    client = srv.app.test_client()
    resp = client.get("/query?type=alerts&status=list")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["state"] == "ok"
    assert "open_alerts" in data
