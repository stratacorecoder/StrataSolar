'''QA PR13 regressions: missed dead inverter, nightly low-SOC, MPPT shading, modes.'''

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from equipment_helpers import EquipmentLab

MNL = ZoneInfo('Asia/Manila')


def _forecast(lab, hourly, source='open_meteo'):
    return {'state': 'ok', 'source': source, 'today': lab.when.date().isoformat(),
            'generated_at': lab.when.astimezone(timezone.utc).isoformat(),
            'today_forecast_kwh': sum(hourly), 'hourly_today': list(hourly)}


@pytest.mark.parametrize('forecast', ['missing', 'history', 'dim_monsoon'])
def test_dead_inverter_detected_without_usable_forecast(monkeypatch, forecast):
    lab = EquipmentLab(monkeypatch, datetime(2026, 7, 23, 9, tzinfo=MNL))
    lab.device.current_power_produced_kw = 0.0
    lab.device.pv_dc_power_kw = 0.0
    lab.device.inverter_ac_power_kw = 0.0
    lab.device.battery_power_kw = 0.0
    dim = [0] * 7 + [0.13, 0.8, 1.05, 1.1, 0.9, 1.0, 0.8, 0.75, 0.5, 0.36, 0.19] + [0] * 6
    if forecast == 'history':
        lab.forecast = _forecast(lab, dim, source='history')
    elif forecast == 'dim_monsoon':
        lab.forecast = _forecast(lab, dim)
    lab.run(50, lambda r: setattr(r.device, 'battery_soc_percent', 60.0))
    assert 'zero_production_daylight' in lab.rules()
    lab.close()


def test_zero_production_still_quiet_at_night_and_low_sun(monkeypatch):
    lab = EquipmentLab(monkeypatch, datetime(2026, 4, 15, 17, 30, tzinfo=MNL))
    lab.device.current_power_produced_kw = 0.0
    lab.run(13 * 60, lambda r: setattr(r.device, 'battery_soc_percent', 60.0))
    assert 'zero_production_daylight' not in lab.rules(None)
    lab.close()


def test_battery_reserve_at_night_is_not_an_alert_by_default(monkeypatch):
    lab = EquipmentLab(monkeypatch, datetime(2026, 4, 15, 22, tzinfo=MNL))
    lab.device.battery_soc_percent = 5.0
    lab.device.battery_power_kw = 0.0
    lab.device.battery_mode = 'nearly depleted'
    lab.run(60, lambda r: setattr(r.device, 'battery_soc_percent', 5.0))
    assert 'battery_low_soc' not in lab.rules(None)
    lab.config.config_data['alerts']['battery_low_soc_enabled'] = True
    lab.run(5, lambda r: setattr(r.device, 'battery_soc_percent', 5.0))
    assert 'battery_low_soc' in lab.rules()
    lab.close()


def test_morning_string_shading_is_not_an_mppt_fault(monkeypatch):
    lab = EquipmentLab(monkeypatch, datetime(2026, 4, 15, 7, tzinfo=MNL))

    def shade(r):
        r.device.pv_mppt_power_kw = [2.0, 0.3 if r.when.hour < 10 else 2.0]
    lab.run(5 * 60, shade)
    assert 'panels_mppt_imbalance' not in lab.rules(None)
    lab.close()


def test_open_string_at_midday_is_still_an_mppt_fault(monkeypatch):
    lab = EquipmentLab(monkeypatch, datetime(2026, 4, 15, 11, 30, tzinfo=MNL))
    lab.run(30, lambda r: setattr(r.device, 'pv_mppt_power_kw', [2.0, 0.0]))
    assert 'panels_mppt_imbalance' in lab.rules()
    lab.close()


def test_battery_fault_resolves_when_battery_reports_full(monkeypatch):
    lab = EquipmentLab(monkeypatch)
    lab.device.battery_mode = 'stopped (temperature)'
    lab.run(10)
    assert 'battery_fault' in lab.rules()
    lab.device.battery_mode = 'battery full'
    lab.run(30)
    assert 'battery_fault' not in lab.rules()
    lab.close()


def test_old_firmware_temperature_fault_string(monkeypatch):
    lab = EquipmentLab(monkeypatch)
    lab.device.battery_mode = 'awake but non operable (temperature)'
    lab.run(10)
    assert 'battery_fault' in lab.rules()
    lab.close()


def test_bms_calibration_soc_rewrite_is_not_a_soc_jump(monkeypatch):
    lab = EquipmentLab(monkeypatch)
    lab.device.battery_power_kw = 0.0
    lab.device.battery_mode = 'calibrate'
    lab.run(10, lambda r: setattr(r.device, 'battery_soc_percent',
                                  40.0 + 8 * min(5, r.when.minute)))
    assert 'battery_soc_jump' not in lab.rules(None)
    lab.close()


@pytest.mark.parametrize('mode', ['zero_daylight', 'inverter_dc_without_ac'])
def test_dummy_no_ac_output_reports_no_export(mode):
    from types import SimpleNamespace
    from devices.Dummy import Dummy
    dev = Dummy(SimpleNamespace(config_data={'dummy': {'fault_mode': mode,
                                                       'battery_soc_percent': 60}}))
    dev.update()
    assert dev.current_power_fed_in_kw == 0.0
    assert dev.current_power_consumed_from_pv_kw == 0.0


def test_dummy_soc_jump_does_not_also_stall_charging():
    from types import SimpleNamespace
    from devices.Dummy import Dummy
    dev = Dummy(SimpleNamespace(config_data={'dummy': {'fault_mode': 'battery_soc_jump'}}))
    dev.update()
    assert dev.battery_power_kw > 0.05


def test_component_trigger_is_refreshed_on_migration():
    from database import Database
    from db_migrate import ensure_feature_schema
    db = Database(':memory:')
    ensure_feature_schema(db)
    # Simulate a trigger left behind by an older build with a stale mapping.
    db.execute('DROP TRIGGER alerts_component_insert')
    db.execute("CREATE TRIGGER alerts_component_insert AFTER INSERT ON alerts "
               "WHEN NEW.component='system' BEGIN UPDATE alerts SET component='system' "
               "WHERE id=NEW.id; END")
    ensure_feature_schema(db)
    sql = db.execute("SELECT sql FROM sqlite_master WHERE name='alerts_component_insert'")[0][0]
    assert "WHEN 'battery_fault' THEN 'battery'" in sql
    db.close()
