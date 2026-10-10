'''Optional telemetry retained only when supplied by a successful driver read.'''

import math

EQUIPMENT_FIELDS = (
    'pv_dc_power_kw', 'inverter_ac_power_kw', 'pv_mppt_power_kw',
    'battery_soc_percent', 'battery_power_kw', 'battery_mode',
    'battery_max_soc_percent',
)


def finite_number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return number if math.isfinite(number) else None
