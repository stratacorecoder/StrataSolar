'''Audit-backed mappings: no added HTTP requests/registers or invented readings.'''

from types import SimpleNamespace

import pytest

from aggregates import touch_device_success_heartbeat
from database import Database
from db_migrate import ensure_feature_schema
from device_snapshot import snapshot_from_db
from devices.Dummy import Dummy
from devices.Fronius import Fronius
from equipment_helpers import EquipmentLab
from feature_settings import alerts_settings
from test_equipment_alerts import RULES


def _powerflow(inverter=None, site=None):
    base = {'E_Total': 100000, 'P_PV': 3000, 'P_Grid': -500, 'P_Akku': -800}
    base.update(site or {})
    return {'Body': {'Data': {'Site': base, 'Inverters': {'1': inverter or {
        'DT': 99, 'P': 2200, 'SOC': 60, 'Battery_Mode': 'normal'}}}}}


def test_fronius_retains_dc_ac_and_battery_fields_and_sign():
    dev = Fronius.__new__(Fronius)
    dev.has_meter = False
    dev.copy_data(_powerflow(), {})
    assert dev.inverter_ac_power_kw == 2.2
    assert dev.pv_dc_power_kw == 3
    assert dev.battery_soc_percent == 60
    assert dev.battery_power_kw == -0.8
    assert dev.battery_mode == 'normal'
    assert not hasattr(dev, 'inverter_temperature_c')
    assert not hasattr(dev, 'battery_voltage_v')


def test_fronius_missing_null_or_multiple_inverters_reset_optional_fields():
    dev = Fronius.__new__(Fronius)
    dev.has_meter = False
    dev.copy_data(_powerflow(), {})
    payload = _powerflow({'DT': 99, 'P': None, 'SOC': None}, {'P_PV': None, 'P_Akku': None})
    dev.copy_data(payload, {})
    assert all(getattr(dev, field) is None for field in (
        'pv_dc_power_kw', 'inverter_ac_power_kw', 'battery_soc_percent', 'battery_power_kw', 'battery_mode'))
    payload = _powerflow()
    payload['Body']['Data']['Inverters']['2'] = dict(payload['Body']['Data']['Inverters']['1'])
    dev.copy_data(payload, {})
    assert dev.battery_soc_percent is None
    assert dev.inverter_ac_power_kw is None
    assert dev.pv_dc_power_kw is None


def test_fronius_snapinverter_pv_is_not_claimed_as_dc():
    dev = Fronius.__new__(Fronius)
    dev.has_meter = False
    dev.copy_data(_powerflow({'DT': 123, 'P': 3000}, {'P_Akku': None}), {})
    assert dev.inverter_ac_power_kw == 3
    assert dev.pv_dc_power_kw is None
    assert dev.battery_soc_percent is None


def test_snapshot_copies_optional_values_without_fabricating_from_db():
    db = Database(':memory:')
    ensure_feature_schema(db)
    db.execute('CREATE TABLE current (date TEXT, produced REAL, consumed_total REAL, fed_in REAL)')
    db.execute("INSERT INTO current VALUES ('cur', 3, 1, 2)")
    touch_device_success_heartbeat(db)
    dev = SimpleNamespace(pv_mppt_power_kw=[1.5, 1.5], inverter_ac_power_kw=None,
                          battery_soc_percent=50, battery_power_kw=-0.8, battery_mode='normal')
    snapshot = snapshot_from_db(db, dev)
    dev.pv_mppt_power_kw[0] = 0
    assert snapshot.pv_mppt_power_kw == [1.5, 1.5]
    assert snapshot.battery_power_kw == -0.8
    assert snapshot.inverter_ac_power_kw is None
    assert snapshot.live_telemetry is True
    # The DB-only snapshot has power but no capability to make equipment inferences.
    db.execute('CREATE TABLE all_time (date TEXT, produced_a REAL, produced_b REAL, '
               'consumed_a REAL, consumed_b REAL, fed_in_a REAL, fed_in_b REAL)')
    snapshot = snapshot_from_db(db)
    assert snapshot.live_telemetry is False
    assert not hasattr(snapshot, 'pv_mppt_power_kw')
    assert snapshot.battery_soc_percent is None
    db.close()


@pytest.mark.parametrize('rule,delay,missing', RULES)
def test_dummy_fault_modes_trigger_real_evaluator_through_snapshot(monkeypatch, rule, delay, missing):
    lab = EquipmentLab(monkeypatch)
    lab.db.execute('CREATE TABLE current (date TEXT, produced REAL, consumed_total REAL, fed_in REAL)')
    touch_device_success_heartbeat(lab.db)
    dev = Dummy(SimpleNamespace(config_data={'dummy': {'fault_mode': rule}}))

    def sample(replay):
        dev.update()
        replay.device = snapshot_from_db(replay.db, dev)

    lab.run(delay + 3, sample)
    assert rule in lab.rules()
    lab.close()


@pytest.mark.parametrize('key,value', [
    ('battery_capacity_kwh', float('nan')),
    ('equipment_open_minutes', float('inf')),
    ('panels_mppt_capacity_kw', [4, 0]),
    ('panels_mppt_capacity_kw', '4,4'),
])
def test_equipment_config_rejects_invalid_numbers(key, value):
    from config import ConfigError
    with pytest.raises(ConfigError):
        alerts_settings({'alerts': {key: value}})
