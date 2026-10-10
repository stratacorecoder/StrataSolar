'''Equipment rules debounce, hold unknown samples and require measured recovery.'''

from types import SimpleNamespace

import pytest

from alert_engine import list_alerts
from equipment_helpers import EquipmentLab, healthy_device


RULES = [
    ('inverter_dc_without_ac', 5, 'inverter_ac_power_kw'),
    ('panels_mppt_imbalance', 15, 'pv_mppt_power_kw'),
    ('battery_fault', 5, 'battery_mode'),
    ('battery_soc_jump', 2, 'battery_power_kw'),
    ('battery_charge_stalled', 30, 'battery_power_kw'),
]


def fault(rule, lab):
    dev = lab.device
    if rule == 'inverter_dc_without_ac':
        dev.inverter_ac_power_kw = 0
        dev.battery_power_kw = 0
    elif rule == 'panels_mppt_imbalance':
        dev.pv_mppt_power_kw = [2, 0.02]
    elif rule == 'battery_fault':
        dev.battery_mode = 'non operable (temperature)'
    elif rule == 'battery_soc_jump':
        dev.battery_power_kw = 0
        dev.battery_soc_percent = 50 if lab.when.minute % 2 else 70
    elif rule == 'battery_charge_stalled':
        dev.battery_power_kw = 0


@pytest.mark.parametrize('rule,delay,missing', RULES)
def test_equipment_rule_debounce_one_open_alert_and_clear_period(monkeypatch, rule, delay, missing):
    lab = EquipmentLab(monkeypatch)
    fault(rule, lab)
    lab.evaluate()
    extra = 1 if rule == 'battery_soc_jump' else 0
    lab.run(delay - 1 + extra, lambda replay: fault(rule, replay))
    assert rule not in lab.rules()
    lab.tick(lambda replay: fault(rule, replay))
    assert rule in lab.rules()
    alert_id = next(a['id'] for a in list_alerts(lab.db, 'open') if a['rule_id'] == rule)
    lab.run(4, lambda replay: fault(rule, replay))
    assert [a['id'] for a in list_alerts(lab.db, 'open') if a['rule_id'] == rule] == [alert_id]
    lab.device = healthy_device()
    lab.evaluate()
    # SOC discontinuities need one further normal sample after resetting SOC.
    if rule == 'battery_soc_jump':
        lab.tick()
    lab.run(4)
    assert rule in lab.rules()
    lab.tick()
    assert rule not in lab.rules()
    assert rule in lab.rules('resolved')
    lab.close()


@pytest.mark.parametrize('rule,delay,missing', RULES)
def test_missing_telemetry_pauses_pending_and_holds_open_fault(monkeypatch, rule, delay, missing):
    lab = EquipmentLab(monkeypatch)
    fault(rule, lab)
    lab.evaluate()
    lab.run(1, lambda replay: fault(rule, replay))
    setattr(lab.device, missing, None)
    lab.run(delay + 5)
    assert rule not in lab.rules()
    lab.device = healthy_device()
    fault(rule, lab)
    lab.evaluate()
    assert rule not in lab.rules()
    lab.run(delay + 2, lambda replay: fault(rule, replay))
    assert rule in lab.rules()
    setattr(lab.device, missing, None)
    lab.run(10)
    assert rule in lab.rules()
    lab.close()


@pytest.mark.parametrize('rule,delay,missing', RULES)
def test_transient_fault_and_stale_sample_do_not_open(monkeypatch, rule, delay, missing):
    lab = EquipmentLab(monkeypatch)
    fault(rule, lab)
    lab.evaluate()
    lab.device = healthy_device()
    lab.run(delay + 2)
    assert rule not in lab.rules()
    fault(rule, lab)
    lab.device_age = 3600
    lab.run(delay + 2, lambda replay: fault(rule, replay))
    assert rule not in lab.rules()
    lab.close()


def test_all_optional_rules_silent_on_legacy_driver(monkeypatch):
    lab = EquipmentLab(monkeypatch)
    lab.device = SimpleNamespace(current_power_produced_kw=3)
    lab.run(180)
    assert not lab.rules()
    lab.close()


def test_dc_routed_to_battery_is_not_an_ac_fault(monkeypatch):
    lab = EquipmentLab(monkeypatch)
    lab.device.inverter_ac_power_kw = 0
    lab.device.pv_dc_power_kw = 3
    lab.device.battery_power_kw = -3
    lab.device.current_power_fed_in_kw = 0
    lab.run(20)
    assert 'inverter_dc_without_ac' not in lab.rules()
    lab.close()


def test_mppt_capacities_are_required_and_normalize_unequal_strings(monkeypatch):
    lab = EquipmentLab(monkeypatch)
    lab.device.pv_mppt_power_kw = [3, 0.3]
    lab.config.config_data['alerts']['panels_mppt_capacity_kw'] = []
    lab.run(20)
    assert 'panels_mppt_imbalance' not in lab.rules()
    lab.config.config_data['alerts']['panels_mppt_capacity_kw'] = [6, 0.6]
    lab.run(20)
    assert 'panels_mppt_imbalance' not in lab.rules()
    lab.close()


@pytest.mark.parametrize('mode,soc,export', [
    ('normal', 99, 2), ('suspended', 50, 2), ('disabled', 50, 2),
    ('calibrate', 50, 2), ('normal', 50, 0),
])
def test_full_scheduled_or_no_surplus_battery_is_not_stalled(monkeypatch, mode, soc, export):
    lab = EquipmentLab(monkeypatch)
    lab.device.battery_power_kw = 0
    lab.device.battery_soc_percent = soc
    lab.device.battery_mode = mode
    lab.device.current_power_fed_in_kw = export
    lab.run(40)
    assert 'battery_charge_stalled' not in lab.rules()
    lab.close()


def test_charge_stall_is_opt_in(monkeypatch):
    lab = EquipmentLab(monkeypatch)
    lab.config.config_data['alerts'].pop('battery_charge_stalled_enabled')
    lab.device.battery_power_kw = 0
    lab.run(40)
    assert 'battery_charge_stalled' not in lab.rules()
    lab.close()


def test_soc_change_explained_by_power_and_capacity_is_not_a_jump(monkeypatch):
    lab = EquipmentLab(monkeypatch)
    # A small test battery moves 10 SOC points per minute. This exceeds the
    # fixed 5-point tolerance and must be explained by measured energy.
    lab.config.config_data['alerts']['battery_capacity_kwh'] = 1
    lab.device.battery_power_kw = -6
    lab.device.current_power_fed_in_kw = 0
    lab.evaluate()
    lab.run(20)
    assert 'battery_soc_jump' not in lab.rules()
    lab.close()


@pytest.mark.parametrize('mode', [
    'none operable', 'non operable (voltage)', 'non operable (temperature)', 'stopped (temperature)',
])
def test_documented_battery_fault_modes_alert_even_at_night(monkeypatch, mode):
    lab = EquipmentLab(monkeypatch)
    lab.when = lab.when.replace(hour=22)
    lab.device.battery_mode = mode
    lab.run(6)
    assert 'battery_fault' in lab.rules()
    lab.close()


def test_soc_unknown_capacity_or_gap_cannot_establish_bms_fault(monkeypatch):
    lab = EquipmentLab(monkeypatch)
    lab.config.config_data['alerts']['battery_capacity_kwh'] = None
    lab.run(10, lambda replay: fault('battery_soc_jump', replay))
    assert 'battery_soc_jump' not in lab.rules()
    lab.config.config_data['alerts']['battery_capacity_kwh'] = 10
    lab.when = lab.when.replace(hour=10)
    fault('battery_soc_jump', lab)
    lab.evaluate()
    assert 'battery_soc_jump' not in lab.rules()
    lab.close()


def test_hysteresis_requires_stronger_ac_and_mppt_recovery(monkeypatch):
    lab = EquipmentLab(monkeypatch)
    fault('inverter_dc_without_ac', lab)
    fault('panels_mppt_imbalance', lab)
    lab.evaluate()
    lab.run(16)
    assert {'inverter_dc_without_ac', 'panels_mppt_imbalance'} <= lab.rules()
    lab.device.inverter_ac_power_kw = 0.1
    lab.device.pv_mppt_power_kw = [2, 0.6]
    lab.run(6)
    assert {'inverter_dc_without_ac', 'panels_mppt_imbalance'} <= lab.rules()
    lab.device.inverter_ac_power_kw = 3
    lab.device.pv_mppt_power_kw = [2, 2]
    lab.evaluate()
    lab.run(5)
    assert not {'inverter_dc_without_ac', 'panels_mppt_imbalance'} & lab.rules()
    lab.close()


@pytest.mark.parametrize('rule,delay,missing', [RULES[0], RULES[1], RULES[4]])
def test_daylight_equipment_rules_do_not_fire_at_night(monkeypatch, rule, delay, missing):
    lab = EquipmentLab(monkeypatch)
    lab.when = lab.when.replace(hour=22)
    fault(rule, lab)
    lab.run(delay + 2)
    assert rule not in lab.rules()
    lab.close()
