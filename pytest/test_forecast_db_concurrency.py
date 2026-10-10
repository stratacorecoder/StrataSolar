'''Forecast refresh must not hold SQLite locks across network I/O.'''

import threading
import time
from datetime import date, timedelta

from aggregates import touch_grabber_loop_heartbeat
from config import Config
from database import Database
from db_migrate import ensure_feature_schema
from forecast_service import refresh_forecast_if_due


def _config(tmp_path):
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
forecast:
  enabled: true
  latitude: 52.0
  longitude: 13.0
  panel_capacity_kw: 5
  min_history_days: 1
  refresh_interval_s: 300
  open_meteo_timeout_s: 30
"""
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return Config(str(path))


def _seed_days(tmp_path):
    (tmp_path / "data").mkdir(exist_ok=True)
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    start = date.today() - timedelta(days=5)
    for i in range(5):
        d = (start + timedelta(days=i)).isoformat()
        db.execute_params_no_result(
            "INSERT INTO days VALUES (?, 0, 5, 0, 3, 0, 1)", (d,))
    db.close()


def test_grabber_heartbeat_while_forecast_network_slow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    _seed_days(tmp_path)
    cfg = _config(tmp_path)
    errors = []
    stop = threading.Event()

    def slow_fetch(*_args, **_kwargs):
        time.sleep(1.5)
        return None

    def heartbeat_loop():
        while not stop.is_set():
            try:
                db = Database("data/db.sqlite")
                touch_grabber_loop_heartbeat(db)
                db.close()
            except Exception as exc:
                errors.append(exc)
            time.sleep(0.05)

    monkeypatch.setattr("forecast_service._fetch_open_meteo", slow_fetch)
    t = threading.Thread(target=heartbeat_loop, daemon=True)
    t.start()
    refresh_forecast_if_due(cfg, "UTC", 0.0, time.monotonic())
    stop.set()
    t.join(timeout=3)
    assert not errors, errors


def test_forecast_api_never_uses_network(monkeypatch, tmp_path):
    import server as srv

    def fail_network(*_a, **_k):
        raise AssertionError("forecast API must not call Open-Meteo")

    monkeypatch.chdir(tmp_path)
    _seed_days(tmp_path)
    cfg = _config(tmp_path)
    monkeypatch.setattr(srv, "config", cfg)
    monkeypatch.setattr("forecast_service._fetch_open_meteo", fail_network)
    client = srv.app.test_client()
    resp = client.get("/query?type=forecast")
    assert resp.status_code == 200
    import json
    data = json.loads(resp.data)
    assert data["state"] in ("pending", "insufficient_history", "disabled")
