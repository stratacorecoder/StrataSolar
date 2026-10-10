'''Optional forecast and alert settings with defaults.'''

import math

from azimuth import compass_azimuth_to_open_meteo, validate_open_meteo_azimuth
from config import ConfigError


def _num(value, key, minimum=None, maximum=None):
    if value is None:
        raise ConfigError(f"{key} must be a number")
    try:
        n = float(value)
    except (TypeError, ValueError):
        raise ConfigError(f"{key} must be a number") from None
    if not math.isfinite(n):
        raise ConfigError(f"{key} must be finite")
    if minimum is not None and n < minimum:
        raise ConfigError(f"{key} must be >= {minimum}")
    if maximum is not None and n > maximum:
        raise ConfigError(f"{key} must be <= {maximum}")
    return n


def _int(value, key, minimum=None, maximum=None):
    n = int(_num(value, key))
    if minimum is not None and n < minimum:
        raise ConfigError(f"{key} must be >= {minimum}")
    if maximum is not None and n > maximum:
        raise ConfigError(f"{key} must be <= {maximum}")
    return n


def _bool(value, default):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    raise ConfigError("expected boolean")


def forecast_settings(config_data):
    block = config_data.get('forecast')
    if block is None:
        block = {}
    if not isinstance(block, dict):
        raise ConfigError("forecast must be a mapping")

    lat = block.get('latitude')
    lon = block.get('longitude')
    if lat is not None:
        lat = _num(lat, 'forecast.latitude', -90, 90)
    if lon is not None:
        lon = _num(lon, 'forecast.longitude', -180, 180)

    result = {
        'enabled': _bool(block.get('enabled'), True),
        'latitude': lat,
        'longitude': lon,
        'panel_capacity_kw': _num(
            block.get('panel_capacity_kw', 5.0),
            'forecast.panel_capacity_kw', 0.01, 10000),
        'panel_tilt_deg': _num(
            block.get('panel_tilt_deg', 15),
            'forecast.panel_tilt_deg', 0, 90),
        'panel_azimuth_deg': _num(
            block.get('panel_azimuth_deg', 180),
            'forecast.panel_azimuth_deg', 0, 360),
        'system_loss_factor': _num(
            block.get('system_loss_factor', 0.85),
            'forecast.system_loss_factor', 0.1, 1.0),
        'history_days_calibration': _int(
            block.get('history_days_calibration', 14),
            'forecast.history_days_calibration', 3, 90),
        'history_days_fallback': _int(
            block.get('history_days_fallback', 28),
            'forecast.history_days_fallback', 1, 365),
        'forecast_days': _int(
            block.get('forecast_days', 7),
            'forecast.forecast_days', 1, 16),
        'open_meteo_timeout_s': _int(
            block.get('open_meteo_timeout_s', 15),
            'forecast.open_meteo_timeout_s', 3, 60),
        'refresh_interval_s': _int(
            block.get('refresh_interval_s', 3600),
            'forecast.refresh_interval_s', 300, 86400),
        'min_history_days': _int(
            block.get('min_history_days', 3),
            'forecast.min_history_days', 1, 30),
    }
    om = compass_azimuth_to_open_meteo(result['panel_azimuth_deg'])
    validate_open_meteo_azimuth(om)
    result['panel_azimuth_open_meteo'] = om
    return result


def alerts_settings(config_data):
    block = config_data.get('alerts')
    if block is None:
        block = {}
    if not isinstance(block, dict):
        raise ConfigError("alerts must be a mapping")

    qs_raw = block.get('device_unreachable_quiet_start_hour')
    qe_raw = block.get('device_unreachable_quiet_end_hour')
    if (qs_raw is not None) != (qe_raw is not None):
        raise ConfigError(
            "alerts.device_unreachable_quiet_start_hour and "
            "device_unreachable_quiet_end_hour must be set together")

    capacities = block.get('panels_mppt_capacity_kw') or []
    if not isinstance(capacities, list) or len(capacities) > 16:
        raise ConfigError('alerts.panels_mppt_capacity_kw must be a list (max 16)')
    capacities = [_num(v, 'alerts.panels_mppt_capacity_kw', 0.01, 10000)
                  for v in capacities]
    battery_capacity = block.get('battery_capacity_kwh')
    if battery_capacity is not None:
        battery_capacity = _num(battery_capacity, 'alerts.battery_capacity_kwh', 0.1, 10000)

    return {
        'enabled': _bool(block.get('enabled'), True),
        'daylight_rules_enabled': _bool(
            block.get('daylight_rules_enabled'), False),
        'daylight_sun_elevation_deg': _num(
            block.get('daylight_sun_elevation_deg', 5.0),
            'alerts.daylight_sun_elevation_deg', 0, 30),
        'evaluate_interval_s': _int(
            block.get('evaluate_interval_s', 60),
            'alerts.evaluate_interval_s', 15, 3600),
        'device_stale_multiplier': _num(
            block.get('device_stale_multiplier', 6),
            'alerts.device_stale_multiplier', 2, 60),
        'device_stale_min_s': _int(
            block.get('device_stale_min_s', 120),
            'alerts.device_stale_min_s', 30, 3600),
        'daylight_start_hour': _int(
            block.get('daylight_start_hour', 8),
            'alerts.daylight_start_hour', 4, 12),
        'daylight_end_hour': _int(
            block.get('daylight_end_hour', 18),
            'alerts.daylight_end_hour', 14, 22),
        'zero_production_kw': _num(
            block.get('zero_production_kw', 0.05),
            'alerts.zero_production_kw', 0, 1),
        'zero_production_minutes': _int(
            block.get('zero_production_minutes', 45),
            'alerts.zero_production_minutes', 15, 240),
        'below_forecast_fraction': _num(
            block.get('below_forecast_fraction', 0.35),
            'alerts.below_forecast_fraction', 0.05, 0.95),
        'below_forecast_min_kwh': _num(
            block.get('below_forecast_min_kwh', 2.0),
            'alerts.below_forecast_min_kwh', 0, 100),
        'below_forecast_after_hour': _int(
            block.get('below_forecast_after_hour', 14),
            'alerts.below_forecast_after_hour', 10, 20),
        'production_underperformance_minutes': _int(
            block.get('production_underperformance_minutes', 30),
            'alerts.production_underperformance_minutes', 5, 240),
        'production_weather_min_fraction': _num(
            block.get('production_weather_min_fraction', 0.15),
            'alerts.production_weather_min_fraction', 0.01, 0.8),
        'baseline_below_fraction': _num(
            block.get('baseline_below_fraction', 0.45),
            'alerts.baseline_below_fraction', 0.1, 0.95),
        'baseline_min_history_days': _int(
            block.get('baseline_min_history_days', 7),
            'alerts.baseline_min_history_days', 3, 90),
        'spike_multiplier': _num(
            block.get('spike_multiplier', 4.0),
            'alerts.spike_multiplier', 2, 20),
        'spike_min_delta_kwh': _num(
            block.get('spike_min_delta_kwh', 5.0),
            'alerts.spike_min_delta_kwh', 0.5, 100),
        'consumption_spike_multiplier': _num(
            block.get('consumption_spike_multiplier', 3.5),
            'alerts.consumption_spike_multiplier', 2, 20),
        'consumption_spike_enabled': _bool(
            block.get('consumption_spike_enabled'), False),
        'consumption_spike_min_kwh': _num(
            block.get('consumption_spike_min_kwh', 8.0),
            'alerts.consumption_spike_min_kwh', 1, 200),
        'battery_low_soc_percent': _num(
            block.get('battery_low_soc_percent', 10),
            'alerts.battery_low_soc_percent', 1, 50),
        'battery_stuck_minutes': _int(
            block.get('battery_stuck_minutes', 120),
            'alerts.battery_stuck_minutes', 30, 720),
        'battery_stuck_min_power_kw': _num(
            block.get('battery_stuck_min_power_kw', 0.2),
            'alerts.battery_stuck_min_power_kw', 0.01, 20),
        'equipment_open_minutes': _int(
            block.get('equipment_open_minutes', 5),
            'alerts.equipment_open_minutes', 1, 60),
        'inverter_dc_min_kw': _num(
            block.get('inverter_dc_min_kw', 0.5),
            'alerts.inverter_dc_min_kw', 0.1, 100),
        'inverter_ac_zero_kw': _num(
            block.get('inverter_ac_zero_kw', 0.05),
            'alerts.inverter_ac_zero_kw', 0, 1),
        'panels_mppt_capacity_kw': capacities,
        'panels_mppt_min_fraction': _num(
            block.get('panels_mppt_min_fraction', 0.2),
            'alerts.panels_mppt_min_fraction', 0.05, 1),
        'panels_mppt_below_fraction': _num(
            block.get('panels_mppt_below_fraction', 0.25),
            'alerts.panels_mppt_below_fraction', 0.05, 0.7),
        'panels_mppt_minutes': _int(
            block.get('panels_mppt_minutes', 15),
            'alerts.panels_mppt_minutes', 5, 120),
        'battery_capacity_kwh': battery_capacity,
        'battery_soc_jump_percent': _num(
            block.get('battery_soc_jump_percent', 5),
            'alerts.battery_soc_jump_percent', 2, 50),
        'battery_soc_jump_minutes': _int(
            block.get('battery_soc_jump_minutes', 2),
            'alerts.battery_soc_jump_minutes', 1, 30),
        'battery_charge_stalled_enabled': _bool(
            block.get('battery_charge_stalled_enabled'), False),
        'battery_charge_surplus_kw': _num(
            block.get('battery_charge_surplus_kw', 0.5),
            'alerts.battery_charge_surplus_kw', 0.1, 100),
        'battery_charge_stalled_minutes': _int(
            block.get('battery_charge_stalled_minutes', 30),
            'alerts.battery_charge_stalled_minutes', 5, 240),
        'resolve_clear_minutes': _int(
            block.get('resolve_clear_minutes', 20),
            'alerts.resolve_clear_minutes', 5, 180),
        'device_unreachable_night_suppress': _bool(
            block.get('device_unreachable_night_suppress'), True),
        'device_unreachable_sunrise_grace_minutes': _int(
            block.get('device_unreachable_sunrise_grace_minutes', 60),
            'alerts.device_unreachable_sunrise_grace_minutes', 0, 240),
        'device_unreachable_quiet_start_hour': (
            _int(qs_raw, 'alerts.device_unreachable_quiet_start_hour', 0, 23)
            if qs_raw is not None else None),
        'device_unreachable_quiet_end_hour': (
            _int(qe_raw, 'alerts.device_unreachable_quiet_end_hour', 0, 23)
            if qe_raw is not None else None),
        'baseline_consecutive_days': _int(
            block.get('baseline_consecutive_days', 2),
            'alerts.baseline_consecutive_days', 1, 7),
    }
