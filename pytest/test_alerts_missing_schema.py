import json

import server as srv
from config import Config


def test_alerts_query_empty_without_migration(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text("""
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
""", encoding="utf-8")
    monkeypatch.setattr(srv, "config", Config(str(cfg_path)))
    resp = srv.app.test_client().get("/query?type=alerts&status=list")
    assert resp.status_code == 200
    data = json.loads(resp.data)
    assert data["state"] == "ok"
    assert data["open_count"] == 0
    assert data["open_alerts"] == []
