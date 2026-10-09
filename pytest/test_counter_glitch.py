from alert_engine import evaluate_alerts, list_alerts, open_alert_count
from config import Config
from database import Database
from db_migrate import ensure_feature_schema


class _FakeDevice:
    def __init__(self, **kwargs):
        self.current_power_produced_kw = kwargs.get("power", 1.0)
        self.total_energy_produced_kwh = kwargs.get("prod", 100.0)
        self.total_energy_consumed_kwh = kwargs.get("cons", 80.0)
        self.total_energy_fed_in_kwh = kwargs.get("fed", 40.0)
        self.battery_soc_percent = kwargs.get("soc", None)


def _boot(tmp_path):
    (tmp_path / "data").mkdir()
    db = Database("data/db.sqlite")
    db.execute(
        "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
        "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
    db.execute(
        "CREATE TABLE current (date TEXT PRIMARY KEY, produced REAL, consumed_grid REAL, "
        "consumed_pv REAL, consumed_total REAL, fed_in REAL)")
    db.execute("INSERT INTO current VALUES ('cur', 0,0,0,0,0)")
    ensure_feature_schema(db)
    return db


def _cfg(tmp_path):
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
  interval_s: 10
alerts:
  enabled: true
  counter_reset_drop_kwh: 10
"""
    path = tmp_path / "config.yml"
    path.write_text(text, encoding="utf-8")
    return Config(str(path))


def test_upward_glitch_does_not_open_counter_reset(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = _boot(tmp_path)
    cfg = _cfg(tmp_path)
    evaluate_alerts(cfg, db, _FakeDevice(prod=100.0), "UTC", None)
    evaluate_alerts(cfg, db, _FakeDevice(prod=160.0), "UTC", None)
    evaluate_alerts(cfg, db, _FakeDevice(prod=100.0), "UTC", None)
    assert open_alert_count(db) == 0
    db.close()


def test_small_up_glitch_no_false_reset(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = _boot(tmp_path)
    cfg = _cfg(tmp_path)
    evaluate_alerts(cfg, db, _FakeDevice(prod=100.0), "UTC", None)
    evaluate_alerts(cfg, db, _FakeDevice(prod=112.0), "UTC", None)
    evaluate_alerts(cfg, db, _FakeDevice(prod=100.0), "UTC", None)
    assert open_alert_count(db) == 0
    db.close()


def test_glitch_to_zero_then_real_reset(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = _boot(tmp_path)
    cfg = _cfg(tmp_path)
    evaluate_alerts(cfg, db, _FakeDevice(prod=200.0), "UTC", None)
    evaluate_alerts(cfg, db, _FakeDevice(prod=0.0), "UTC", None)
    evaluate_alerts(cfg, db, _FakeDevice(prod=200.0), "UTC", None)
    evaluate_alerts(cfg, db, _FakeDevice(prod=50.0), "UTC", None)
    evaluate_alerts(cfg, db, _FakeDevice(prod=50.0), "UTC", None)
    assert any(
        a["rule_id"] == "counter_reset" for a in list_alerts(db, "open"))
    db.close()


def test_real_drop_opens_after_two_evaluations(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    db = _boot(tmp_path)
    cfg = _cfg(tmp_path)
    evaluate_alerts(cfg, db, _FakeDevice(prod=200.0), "UTC", None)
    evaluate_alerts(cfg, db, _FakeDevice(prod=50.0), "UTC", None)
    evaluate_alerts(cfg, db, _FakeDevice(prod=50.0), "UTC", None)
    assert any(
        a["rule_id"] == "counter_reset" for a in list_alerts(db, "open"))
    db.close()
