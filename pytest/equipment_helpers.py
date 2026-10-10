'''Minute-by-minute Manila replay clock with real alert debounce durations.'''

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from alert_engine import evaluate_alerts, list_alerts
from database import Database
from db_migrate import ensure_feature_schema


def healthy_device():
    return SimpleNamespace(
        current_power_produced_kw=4.0, current_power_fed_in_kw=1.0,
        current_power_consumed_total_kw=2.0, pv_dc_power_kw=4.0,
        inverter_ac_power_kw=3.0, pv_mppt_power_kw=[2.0, 2.0],
        battery_soc_percent=60.0, battery_power_kw=-0.8, battery_mode='normal')


class EquipmentLab:
    def __init__(self, monkeypatch, when=None):
        self.when = when or datetime(2026, 4, 15, 12, tzinfo=ZoneInfo('Asia/Manila'))
        self.device_age = 0
        self.forecast = None
        self.device = healthy_device()
        self.config = SimpleNamespace(config_data={
            'time_zone': 'Asia/Manila', 'grabber': {'interval_s': 60},
            'forecast': {'latitude': 14.68, 'longitude': 120.54, 'panel_capacity_kw': 8},
            'alerts': {'resolve_clear_minutes': 5, 'panels_mppt_capacity_kw': [4, 4],
                       'battery_capacity_kwh': 10, 'battery_charge_stalled_enabled': True}})
        self.db = Database(':memory:')
        self.db.execute(
            "CREATE TABLE days (date TEXT PRIMARY KEY, produced_a REAL, produced_b REAL, "
            "consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)")
        ensure_feature_schema(self.db)
        for offset in range(1, 15):
            self.db.execute_params_no_result(
                'INSERT INTO days VALUES (?, 0, 32, 0, 15, 0, 10)',
                ((self.when.date() - timedelta(days=offset)).isoformat(),))
        self.set_production(0)
        monkeypatch.setattr('alert_engine.local_now', lambda _: self.when)
        monkeypatch.setattr('alert_engine.local_today', lambda _: self.when.date())
        monkeypatch.setattr('alert_engine._utc_now_iso', lambda: self.when.astimezone(timezone.utc).isoformat())
        monkeypatch.setattr('alert_engine._minutes_since', lambda stamp: (
            self.when - datetime.fromisoformat(stamp)).total_seconds() / 60 if stamp else 0)
        monkeypatch.setattr('alert_engine.device_success_age_seconds', lambda _: self.device_age)

    def set_production(self, kwh):
        self.db.execute_params_no_result(
            'INSERT OR REPLACE INTO days VALUES (?, 0, ?, 0, 15, 0, 10)',
            (self.when.date().isoformat(), kwh))

    def evaluate(self):
        return evaluate_alerts(self.config, self.db, self.device, 'Asia/Manila', self.forecast)

    def tick(self, update=None):
        self.when += timedelta(minutes=1)
        soc = getattr(self.device, 'battery_soc_percent', None)
        power = getattr(self.device, 'battery_power_kw', None)
        if soc is not None and power is not None:
            capacity = self.config.config_data['alerts'].get('battery_capacity_kwh') or 10
            self.device.battery_soc_percent = min(100, max(0, soc - power / capacity * 100 / 60))
        if update:
            update(self)
        return self.evaluate()

    def run(self, minutes, update=None):
        for _ in range(minutes):
            self.tick(update)

    def rules(self, status='open'):
        return {alert['rule_id'] for alert in list_alerts(self.db, status)}

    def close(self):
        self.db.close()
