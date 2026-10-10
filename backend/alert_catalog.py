'''Stable equipment classification shared by storage, migrations and the API.'''

ALERT_COMPONENTS = {
    'device_unreachable': 'inverter',
    'zero_production_daylight': 'inverter',
    'production_below_forecast': 'panels',
    'production_below_baseline': 'panels',
    'battery_low_soc': 'battery',
    'battery_stuck': 'battery',
    'grabber_stale': 'system',
    'production_spike': 'system',
    'consumption_spike': 'system',
    'inverter_dc_without_ac': 'inverter',
    'panels_mppt_imbalance': 'panels',
    'battery_fault': 'battery',
    'battery_soc_jump': 'battery',
    'battery_charge_stalled': 'battery',
}


def alert_component(rule_id):
    return ALERT_COMPONENTS.get(rule_id, 'system')
