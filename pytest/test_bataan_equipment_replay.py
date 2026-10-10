'''Real debounce with realistic weather and driver-format conversion outages.'''

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from alert_engine import list_alerts
from devices.Fronius import Fronius
from equipment_helpers import EquipmentLab, healthy_device
from solar_time import solar_elevation_deg
from test_equipment_alerts import RULES, fault

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/bataan_profiles.json').read_text())
PROFILES = FIXTURE['profiles']
MNL = ZoneInfo('Asia/Manila')


def _forecast(lab, hourly, source='open_meteo'):
    return {'state': 'ok', 'source': source, 'today': lab.when.date().isoformat(),
            'generated_at': lab.when.astimezone(timezone.utc).isoformat(),
            'today_forecast_kwh': sum(hourly), 'hourly_today': list(hourly)}


def _powerflow_device(lab, dc_kw, ac_kw, cumulative, charging_kw):
    # Exercise the real driver mapping, including the DC/AC distinction and
    # P_Akku sign; this is an equipment outage, not a cloud-shaped PV dip.
    dev = Fronius.__new__(Fronius)
    dev.has_meter = False
    dev.copy_data({'Body': {'Data': {
        'Site': {'E_Total': cumulative * 1000, 'P_PV': dc_kw * 1000,
                 'P_Grid': -max(0, ac_kw - 1) * 1000, 'P_Akku': -charging_kw * 1000},
        'Inverters': {'1': {'DT': 99, 'P': ac_kw * 1000,
                            'SOC': lab.device.battery_soc_percent, 'Battery_Mode': 'normal'}},
    }}}, {})
    return dev


@pytest.mark.parametrize('name', ['monsoon_overcast', 'typhoon_near_zero'])
def test_cloud_profiles_keep_realistic_output_above_fifteen_degrees(name):
    profile = PROFILES[name]
    day = datetime.fromisoformat(profile['date']).replace(tzinfo=MNL)
    daylight_kw = [
        output_kw for hour, output_kw in enumerate(profile['hourly_kwh'])
        if solar_elevation_deg(
            FIXTURE['latitude'], FIXTURE['longitude'],
            day + timedelta(hours=hour, minutes=30)) >= 15
    ]
    assert daylight_kw
    assert min(daylight_kw) >= 0.13


@pytest.mark.parametrize('name', list(PROFILES))
def test_bataan_whole_day_weather_replay(monkeypatch, name):
    profile = PROFILES[name]
    start = datetime.fromisoformat(profile['date']).replace(tzinfo=ZoneInfo('Asia/Manila'))
    lab = EquipmentLab(monkeypatch, start)
    hourly = profile['hourly_kwh']
    cumulative = 0
    for minute in range(24 * 60):
        lab.when = start + timedelta(minutes=minute)
        h = lab.when.hour
        lab.forecast = _forecast(lab, hourly)
        dc = hourly[h] / 0.95
        ac = hourly[h] * profile['actual_fraction']
        outage = profile.get('outage_start_hour', 24) <= h < profile.get('outage_end_hour', 24)
        if outage:
            ac = profile['outage_ac_kw']
        charging = min(0.8, max(0, ac - 1)) if not outage and lab.device.battery_soc_percent < 95 else 0
        ac -= charging * 0.95
        soc = lab.device.battery_soc_percent + charging / 10 * 100 / 60
        lab.device = _powerflow_device(lab, dc, ac, cumulative, charging)
        lab.device.battery_soc_percent = min(95, soc)
        # The Fronius driver has no per-MPPT reading. Run the Sunsynk peer
        # check in the same weather replay with physically balanced inputs.
        lab.device.pv_mppt_power_kw = [dc / 2, dc / 2]
        cumulative += ac / 60
        lab.set_production(cumulative)
        lab.evaluate()
    all_rules = lab.rules(None)
    if name == 'partial_inverter_outage':
        assert {'inverter_dc_without_ac', 'production_below_forecast'} <= all_rules
        assert 'inverter_dc_without_ac' not in lab.rules()  # measured afternoon recovery
    else:
        assert not all_rules, f'{name} produced false equipment alerts: {all_rules}'
    assert lab.db.execute('SELECT COUNT(*) FROM notification_outbox')[0][0] == 0
    lab.close()


@pytest.mark.parametrize('rule,delay,missing', RULES)
def test_each_new_fault_replayed_in_clear_bataan_weather(monkeypatch, rule, delay, missing):
    lab = EquipmentLab(monkeypatch)
    hourly = PROFILES['clear_dry_season']['hourly_kwh']
    lab.forecast = _forecast(lab, hourly)
    lab.set_production(10)
    fault(rule, lab)
    lab.evaluate()

    def sample(replay):
        replay.forecast = _forecast(replay, hourly)
        fault(rule, replay)

    lab.run(delay + 2, sample)
    assert rule in lab.rules()
    lab.device = healthy_device()
    lab.evaluate()
    lab.run(7, lambda replay: setattr(replay, 'forecast', _forecast(replay, hourly)))
    assert rule in lab.rules('resolved')
    lab.close()


@pytest.mark.parametrize('source', ['history', 'missing', 'stale', 'previous_day', 'malformed'])
def test_weather_unknown_or_stale_cannot_open_production_faults(monkeypatch, source):
    lab = EquipmentLab(monkeypatch)
    lab.when = lab.when.replace(hour=14)
    lab.device.current_power_produced_kw = 0
    lab.device.pv_dc_power_kw = 0
    lab.device.inverter_ac_power_kw = 0
    lab.device.pv_mppt_power_kw = [0, 0]
    lab.device.battery_power_kw = 0
    hourly = PROFILES['clear_dry_season']['hourly_kwh']
    lab.forecast = _forecast(lab, hourly)
    if source == 'history':
        lab.forecast['source'] = 'history'
    elif source == 'missing':
        lab.forecast = None
    elif source == 'stale':
        lab.forecast['generated_at'] = (lab.when - timedelta(hours=4)).isoformat()
    elif source == 'previous_day':
        lab.forecast['today'] = (lab.when - timedelta(days=1)).date().isoformat()
    else:
        lab.forecast['hourly_today'][14] = None
    lab.config.config_data['alerts']['baseline_consecutive_days'] = 1
    lab.run(60)
    assert not {'production_below_forecast', 'production_below_baseline'} & lab.rules(None)
    # Zero output with the sun high is a dead inverter in any weather; losing
    # the forecast must not disable that check.
    assert 'zero_production_daylight' in lab.rules(None)
    lab.close()


def test_brief_cloud_break_does_not_turn_into_production_alert(monkeypatch):
    lab = EquipmentLab(monkeypatch)
    lab.when = lab.when.replace(hour=14)
    hourly = PROFILES['clear_dry_season']['hourly_kwh']
    lab.forecast = _forecast(lab, hourly)
    lab.device = healthy_device()
    lab.set_production(25)
    lab.device.current_power_produced_kw = 0
    lab.device.pv_dc_power_kw = 0
    lab.device.inverter_ac_power_kw = 0
    lab.device.pv_mppt_power_kw = [0, 0]
    lab.device.battery_power_kw = 0
    lab.run(20)
    assert 'zero_production_daylight' not in lab.rules()
    lab.device = healthy_device()
    lab.run(30)
    assert not lab.rules()
    lab.close()


def test_zero_production_opens_in_bright_bataan_weather_and_needs_output_to_clear(monkeypatch):
    lab = EquipmentLab(monkeypatch)
    lab.when = lab.when.replace(hour=12)
    hourly = PROFILES['clear_dry_season']['hourly_kwh']
    lab.forecast = _forecast(lab, hourly)
    lab.device.current_power_produced_kw = 0
    lab.device.pv_dc_power_kw = 0
    lab.device.inverter_ac_power_kw = 0
    lab.device.pv_mppt_power_kw = [0, 0]
    lab.device.battery_power_kw = 0
    lab.device.current_power_fed_in_kw = 0
    lab.evaluate()
    lab.run(44)
    assert 'zero_production_daylight' not in lab.rules()
    lab.tick()
    assert 'zero_production_daylight' in lab.rules()
    lab.when = lab.when.replace(hour=22)
    lab.run(6)
    assert 'zero_production_daylight' in lab.rules()
    lab.when += timedelta(days=1)
    lab.when = lab.when.replace(hour=12)
    lab.forecast = _forecast(lab, hourly)
    lab.device = healthy_device()
    lab.evaluate()
    lab.run(5)
    assert 'zero_production_daylight' not in lab.rules()
    assert 'zero_production_daylight' in lab.rules('resolved')
    lab.close()


def test_weather_days_break_baseline_streak_and_real_loss_requires_two_days(monkeypatch):
    lab = EquipmentLab(monkeypatch)
    start = lab.when.replace(hour=14)
    for offset, profile_name in enumerate([
            'clear_dry_season', 'monsoon_overcast', 'typhoon_near_zero',
            'clear_dry_season', 'clear_dry_season']):
        lab.when = start + timedelta(days=offset)
        lab.set_production(1)
        hourly = PROFILES[profile_name]['hourly_kwh']
        lab.forecast = _forecast(lab, hourly)
        lab.device = healthy_device()
        lab.device.battery_soc_percent = 95
        lab.device.battery_power_kw = 0
        lab.run(35)
        if offset < 4:
            assert 'production_below_baseline' not in lab.rules(None)
    assert 'production_below_baseline' in lab.rules()
    lab.set_production(40)
    lab.evaluate()
    lab.run(5)
    assert 'production_below_baseline' not in lab.rules()
    assert 'production_below_baseline' in lab.rules('resolved')
    assert all(a['component'] == 'panels' for a in list_alerts(lab.db)
               if a['rule_id'].startswith('production_below'))
    lab.close()
