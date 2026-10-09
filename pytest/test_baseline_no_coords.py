'''Baseline rule without forecast coordinates (default install).'''

import random
from datetime import date, datetime, timedelta, timezone

from alert_engine import evaluate_alerts, list_alerts
from config import Config
from database import Database
from db_migrate import ensure_feature_schema


class _FakeDevice:
    def __init__(self, prod_today=8.0):
        self.current_power_produced_kw = 2.5
        self.total_energy_produced_kwh = 100.0 + prod_today
        self.total_energy_consumed_kwh = 80.0
        self.total_energy_fed_in_kwh = 40.0
        self.battery_soc_percent = None


def _cfg(tmp_path):
    text = """
logging: normal
time_zone: Europe/Madrid
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
  interval_s: 60
alerts:
  enabled: true
  below_forecast_after_hour: 14
  baseline_consecutive_days: 2
  baseline_below_fraction: 0.45
"""
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return Config(str(path))


def test_healthy_site_no_baseline_alerts_without_coords(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    ensure_feature_schema(db)
    rng = random.Random(42)
    start = date(2026, 6, 1)
    for i in range(14):
        d = (start + timedelta(days=i)).isoformat()
        daily = 18.0 + rng.uniform(-3.0, 3.0)
        db.execute_params_no_result(
            "INSERT INTO days VALUES (?, 0, ?, 0, 10, 0, 5)", (d, daily))
    today = (start + timedelta(days=14)).isoformat()
    db.execute_params_no_result(
        "INSERT INTO days VALUES (?, 0, 8, 0, 4, 0, 2)", (today,))
    db.connection.commit()

    cfg = _cfg(tmp_path)
    noon = datetime(2026, 6, 15, 15, 0, tzinfo=timezone.utc)
    monkeypatch.setattr("alert_engine.local_now", lambda _tz: noon)
    monkeypatch.setattr("alert_engine._minutes_since", lambda _iso: 999.0)

    for _ in range(14):
        dev = _FakeDevice(prod_today=8.0)
        evaluate_alerts(cfg, db, dev, "Europe/Madrid", None)

    assert not any(
        a["rule_id"] == "production_below_baseline"
        for a in list_alerts(db, "all"))
    db.close()
