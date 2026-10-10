'''Equipment checks using only retained driver telemetry; no device/network I/O.'''

import json

import alert_engine
from alert_engine import (
    _get_rule_state, _observe_transition, _parse_iso, _set_rule_state,
)
from device_fields import finite_number

# Solar API PowerFlow Battery_Mode values, not API Head.Status (request status).
BATTERY_FAULT_MODES = frozenset({
    'none operable', 'non operable (voltage)', 'non operable (temperature)',
    'stopped (temperature)', 'awake but non operable (temperature)',
})
BATTERY_NORMAL_MODES = frozenset({
    'normal', 'disabled', 'service', 'charge boost', 'nearly depleted',
    'suspended', 'calibrate', 'grid support', 'deplete recovery',
    'preheating', 'startup', 'battery full',
})
# BMS recalibration/maintenance legitimately rewrites SOC.
SOC_REWRITE_MODES = frozenset({'calibrate', 'service', 'startup'})


def _number(device, name):
    return finite_number(getattr(device, name, None))


def _is_open(db, rule):
    return _get_rule_state(db, rule)[0] is not None


def _inverter_dc_without_ac(db, device, settings, daylight, opened):
    rule = 'inverter_dc_without_ac'
    dc = _number(device, 'pv_dc_power_kw')
    ac = _number(device, 'inverter_ac_power_kw')
    battery = _number(device, 'battery_power_kw')
    observed = None
    available = None
    if daylight and None not in (dc, ac, battery) and dc >= 0:
        # DC routed into a charging battery does not need to appear as AC.
        available = dc - max(0.0, -battery)
        limit = settings['inverter_ac_zero_kw'] + (0.1 if _is_open(db, rule) else 0)
        observed = available >= settings['inverter_dc_min_kw'] and ac <= limit
        # Low input cannot prove recovery: retain any open conversion fault.
        if available < settings['inverter_dc_min_kw'] and ac <= limit:
            observed = None
    _observe_transition(
        db, rule, observed, 'DC input without AC output',
        'PV input remains available after battery charging, but AC output is near zero.',
        {'dc_kw': dc, 'ac_kw': ac, 'battery_kw': battery, 'available_dc_kw': available},
        settings, opened, settings['equipment_open_minutes'])


def _panels_mppt_imbalance(db, device, settings, daylight, opened, near_noon=True):
    rule = 'panels_mppt_imbalance'
    powers = getattr(device, 'pv_mppt_power_kw', None)
    capacities = settings['panels_mppt_capacity_kw']
    observed = None
    ratio = None
    valid = isinstance(powers, (list, tuple)) and len(powers) >= 2
    # Only compare strings near solar noon: morning/evening tree or roof
    # shading and E/W orientation differences are not equipment faults.
    if valid and len(powers) == len(capacities) and daylight and near_noon:
        powers = [finite_number(value) for value in powers]
        if all(value is not None and value >= 0 for value in powers):
            normalized = [p / c for p, c in zip(powers, capacities)]
            strongest = max(normalized)
            if strongest >= settings['panels_mppt_min_fraction']:
                ratio = min(normalized) / strongest
                limit = settings['panels_mppt_below_fraction']
                if _is_open(db, rule):
                    limit += 0.15
                observed = ratio < limit
    _observe_transition(
        db, rule, observed, 'PV MPPT imbalance',
        'One comparable PV input is persistently far below its peers in strong light.',
        {'mppt_power_kw': powers, 'capacity_kw': capacities, 'peer_ratio': ratio},
        settings, opened, settings['panels_mppt_minutes'])


def _battery_fault(db, device, settings, opened):
    mode = getattr(device, 'battery_mode', None)
    observed = None
    if isinstance(mode, str) and mode in BATTERY_FAULT_MODES:
        observed = True
    elif isinstance(mode, str) and mode in BATTERY_NORMAL_MODES:
        observed = False
    _observe_transition(
        db, 'battery_fault', observed, 'Battery reports a fault',
        'The battery reports a non-operable voltage or temperature state.',
        {'battery_mode': mode}, settings, opened, settings['equipment_open_minutes'])


def _battery_soc_jump(db, device, settings, opened):
    soc = _number(device, 'battery_soc_percent')
    power = _number(device, 'battery_power_kw')
    capacity = settings['battery_capacity_kwh']
    key = 'battery_soc_jump_sample'
    previous = _get_rule_state(db, key)[3]
    observed = None
    detail = None
    valid = soc is not None and 0 <= soc <= 100 and power is not None and capacity is not None
    if valid:
        now = _parse_iso(alert_engine._utc_now_iso())
        if previous:
            previous = json.loads(previous)
            sampled = _parse_iso(previous.get('sampled_at'))
            elapsed = (now - sampled).total_seconds() if sampled else 0
            # A read gap cannot establish the energy moved between observations.
            max_gap = max(180, 3 * settings['evaluate_interval_s'])
            mode = getattr(device, 'battery_mode', None)
            rewrite = isinstance(mode, str) and mode in SOC_REWRITE_MODES
            if 0 < elapsed <= max_gap and not rewrite:
                delta = soc - previous['soc']
                max_power = max(abs(power), abs(previous['power_kw']))
                energy_bound = max_power * elapsed / 3600 * 100 / capacity * 1.25
                margin = settings['battery_soc_jump_percent']
                wrong_direction = (
                    (power < 0 and previous['power_kw'] < 0 and delta < -margin)
                    or (power > 0 and previous['power_kw'] > 0 and delta > margin))
                observed = abs(delta) > margin + energy_bound or wrong_direction
                detail = {'soc_delta_percent': delta, 'energy_bound_percent': energy_bound,
                          'battery_power_kw': power, 'elapsed_s': elapsed}
        last = {'soc': soc, 'power_kw': power, 'sampled_at': now.isoformat()}
    else:
        last = None
    _set_rule_state(db, key, None, False, None, json.dumps(last) if last else None)
    _observe_transition(
        db, 'battery_soc_jump', observed, 'Battery SOC inconsistent with power',
        'Repeated SOC jumps or drops exceed what measured battery power can explain.',
        detail, settings, opened, settings['battery_soc_jump_minutes'])


def _battery_charge_stalled(db, device, settings, daylight, opened):
    rule = 'battery_charge_stalled'
    soc = _number(device, 'battery_soc_percent')
    power = _number(device, 'battery_power_kw')
    export = _number(device, 'current_power_fed_in_kw')
    pv = _number(device, 'current_power_produced_kw')
    mode = getattr(device, 'battery_mode', None)
    observed = None
    if not settings['battery_charge_stalled_enabled']:
        observed = False
    elif (daylight and None not in (soc, power, export, pv)
          and 0 <= soc <= 100 and isinstance(mode, str) and mode in BATTERY_NORMAL_MODES):
        opening = not _is_open(db, rule)
        configured_limit = settings['battery_charge_limit_soc_percent']
        reported_limit = _number(device, 'battery_max_soc_percent')
        if reported_limit is not None and 1 <= reported_limit <= 100:
            configured_limit = min(configured_limit, reported_limit)
        soc_limit = min(configured_limit, 95 if opening else 98)
        surplus = settings['battery_charge_surplus_kw'] * (1 if opening else 0.5)
        idle_limit = 0.05 if opening else 0.15
        observed = (mode == 'normal' and soc < soc_limit
                    and export >= surplus and pv >= surplus
                    and abs(power) <= idle_limit)
    _observe_transition(
        db, rule, observed, 'Battery is not charging with PV surplus',
        'PV is being exported while the battery remains idle below full charge.',
        {'soc_percent': soc, 'battery_power_kw': power, 'export_kw': export,
         'battery_mode': mode}, settings, opened, settings['battery_charge_stalled_minutes'])


def evaluate_equipment_alerts(db, device, settings, daylight, opened, telemetry_fresh=True,
                              mppt_window=True):
    '''Unknown/stale samples reset pending debounce and hold already-open faults.'''
    if not telemetry_fresh:
        for rule in ('inverter_dc_without_ac', 'panels_mppt_imbalance', 'battery_fault',
                     'battery_soc_jump', 'battery_charge_stalled'):
            _observe_transition(db, rule, None, '', '', None, settings, opened)
        _set_rule_state(db, 'battery_soc_jump_sample', None, False, None, None)
        return
    _inverter_dc_without_ac(db, device, settings, daylight, opened)
    _panels_mppt_imbalance(db, device, settings, daylight, opened, mppt_window)
    _battery_fault(db, device, settings, opened)
    _battery_soc_jump(db, device, settings, opened)
    _battery_charge_stalled(db, device, settings, daylight, opened)
