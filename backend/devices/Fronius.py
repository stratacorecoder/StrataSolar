import requests
import logging

from device_fields import finite_number


# Fronius Symo/Gn24 devices
class Fronius:
    def __init__(self, config):
        # Demo code for config access
        logging.info(f"Fronius device: "
                     f"configured host name is "
                     f"{config.config_data['fronius']['host_name']}")

        self.host_name = config.config_data['fronius']['host_name']

        self.url_inverter = (
            f"http://{self.host_name}/solar_api/v1/GetPowerFlowRealtimeData.fcgi")
        self.url_meter = (
            f"http://{self.host_name}/solar_api/v1/GetMeterRealtimeData.cgi?Scope=System")

        self.has_meter = config.config_data['fronius']['has_meter']  # Smart Meter active?

        # Initialize with default values
        self.total_energy_produced_kwh = 0.0
        self.total_energy_consumed_kwh = 0.0
        self.total_energy_fed_in_kwh = 0.0
        self.current_power_consumed_from_grid_kw = 0.0
        self.current_power_consumed_from_pv_kw = 0.0
        self.current_power_consumed_total_kw = 0.0
        self.current_power_fed_in_kw = 0.0
        self.current_power_produced_kw = 0.0
        self.inverter_ac_power_kw = None
        self.pv_dc_power_kw = None
        self.battery_soc_percent = None
        self.battery_power_kw = None
        self.battery_mode = None

        try:
            self.update()
        except Exception:
            logging.warning(
                "Fronius device: initial connection failed; "
                "will retry in the grabber loop")

    def copy_data(self, inverter_data, meter_data):
        '''Copies the results from the API request.'''
        # Inverter data
        str_total_produced_wh = inverter_data["Body"]["Data"]["Site"]["E_Total"]
        total_produced_kwh = float(str_total_produced_wh) * 0.001
        # Meter data
        if self.has_meter:
            str_total_consumed_from_grid_wh = meter_data["Body"]["Data"]["0"]["EnergyReal_WAC_Plus_Absolute"]
            total_consumed_from_grid_kwh = float(
                str_total_consumed_from_grid_wh) * 0.001
            str_total_fed_in_wh = meter_data["Body"]["Data"]["0"]["EnergyReal_WAC_Minus_Absolute"]
            total_fed_in_kwh = float(str_total_fed_in_wh) * 0.001
        else:
            str_total_consumed_from_grid_wh = 0
            total_consumed_from_grid_kwh = 0
            str_total_fed_in_wh = 0
            total_fed_in_kwh = 0
        # Compute other values
        total_self_consumption_kwh = total_produced_kwh - total_fed_in_kwh
        total_consumption_kwh = total_consumed_from_grid_kwh + total_self_consumption_kwh

        # Logging
        if logging.getLogger().level == logging.DEBUG:
            logging.debug(f"Fronius device: Absolute values:\n"
                          f" - Total produced: {str(total_produced_kwh)} kWh\n"
                          f" - Total grid consumption: {str(total_consumed_from_grid_kwh)} kWh\n"
                          f" - Total self consumption: {str(total_self_consumption_kwh)} kWh\n"
                          f" - Total consumption: {str(total_consumption_kwh)} kWh\n"
                          f" - Total fed in: {str(total_fed_in_kwh)} kWh")

        # Total/absolute values
        self.total_energy_produced_kwh = total_produced_kwh
        self.total_energy_consumed_kwh = total_consumption_kwh
        self.total_energy_fed_in_kwh = total_fed_in_kwh

        # Now extract the momentary values
        str_cur_production_w = inverter_data["Body"]["Data"]["Site"]["P_PV"]
        cur_production_kw = 0.0 if str_cur_production_w is None else float(
            str_cur_production_w) * 0.001
        str_grid_power_w = inverter_data["Body"]["Data"]["Site"]["P_Grid"] or 0
        grid_power_kw = float(str_grid_power_w) * 0.001
        cur_feed_in_kw = (-grid_power_kw) if grid_power_kw < 0.0 else 0.0
        cur_consumption_from_grid = grid_power_kw if grid_power_kw > 0.0 else 0.0
        cur_consumption_from_pv = cur_production_kw - cur_feed_in_kw
        if cur_consumption_from_pv < 0.0:
            cur_consumption_from_pv = 0.0
        cur_consumption_total = cur_consumption_from_grid + cur_consumption_from_pv

        # Logging
        if logging.getLogger().level == logging.DEBUG:
            logging.debug(f"Fronius device: Momentary values:\n"
                          f" - Current production: {str(cur_production_kw)} kW\n"
                          f" - Current feed-in: {str(cur_feed_in_kw)} kW\n"
                          f" - Current consumption from grid: {str(cur_consumption_from_grid)}\n"
                          f" - Current consumption from PV: {str(cur_consumption_from_pv)}\n"
                          f" - Current total consumption: {str(cur_consumption_total)}")

        # Store results
        self.current_power_produced_kw = cur_production_kw
        self.current_power_fed_in_kw = cur_feed_in_kw
        self.current_power_consumed_from_grid_kw = cur_consumption_from_grid
        self.current_power_consumed_from_pv_kw = cur_consumption_from_pv
        self.current_power_consumed_total_kw = cur_consumption_total
        self._copy_equipment_data(inverter_data)

    def _copy_equipment_data(self, inverter_data):
        # No additional HTTP requests: retain optional PowerFlow fields.
        # Never average SOC across batteries or pair site DC/battery power
        # with one of several inverters. Such systems need per-device data.
        data = inverter_data['Body']['Data']
        site = data['Site']
        inverters = data.get('Inverters')
        self.inverter_ac_power_kw = None
        self.pv_dc_power_kw = None
        self.battery_soc_percent = None
        self.battery_power_kw = None
        self.battery_mode = None
        if not isinstance(inverters, dict) or len(inverters) != 1:
            return
        inverter = next(iter(inverters.values()))
        if not isinstance(inverter, dict):
            return
        ac_w = finite_number(inverter.get('P'))
        if ac_w is not None:
            self.inverter_ac_power_kw = ac_w * 0.001
        # P_PV is DC on hybrids; SnapInverters expose AC under the same key.
        # P_Akku + SOC, or Symo Hybrid's DT=99, identifies a hybrid here.
        soc = finite_number(inverter.get('SOC'))
        battery_w = finite_number(site.get('P_Akku'))
        mode = inverter.get('Battery_Mode')
        hybrid = (inverter.get('DT') == 99 or isinstance(mode, str)
                  or (soc is not None and battery_w is not None))
        if not hybrid:
            return
        pv_w = finite_number(site.get('P_PV'))
        self.pv_dc_power_kw = pv_w * 0.001 if pv_w is not None else None
        self.battery_soc_percent = soc if soc is not None and 0 <= soc <= 100 else None
        # Canonical sign is positive discharge, negative charge (Solar API V1).
        self.battery_power_kw = battery_w * 0.001 if battery_w is not None else None
        self.battery_mode = mode.strip().lower() if isinstance(mode, str) else None

    def update(self):
        '''Updates all device stats.'''
        try:
            # Query inverter data
            r_inverter = requests.get(self.url_inverter, timeout=5)
            r_inverter.raise_for_status()
            # Query smart meter data
            if self.has_meter:
                r_meter = requests.get(self.url_meter, timeout=5)
                r_meter.raise_for_status()
                # Extract and process relevant data
                self.copy_data(r_inverter.json(), r_meter.json())
            else:
                self.copy_data(r_inverter.json(), "{}")  # Null meter data
        except requests.exceptions.Timeout:
            logging.error(f"Fronius device: Timeout requesting "
                          f"'{self.url_inverter}' or '{self.url_meter}'")
            raise
        except requests.exceptions.RequestException as e:
            logging.error(f"Fronius device: requests exception {e} for URL "
                          f"'{self.url_inverter}' or '{self.url_meter}'")
            raise
