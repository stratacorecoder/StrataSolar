# Dummy device for testing purposes
from device_fields import finite_number


class Dummy:
    def __init__(self, config):
        if config is None:
            dummy_cfg = {}
        else:
            dummy_cfg = config.config_data.get('dummy') or {}
        if not isinstance(dummy_cfg, dict):
            dummy_cfg = {}
        raw_fault = dummy_cfg.get('fault_mode', '')
        if raw_fault is None or raw_fault is False:
            mode = ''
        else:
            mode = str(raw_fault).lower().strip()
        if mode in ('', 'none', 'off', 'false'):
            mode = ''
        self._fault_mode = mode
        self._tick = 0
        self.battery_soc_percent = finite_number(dummy_cfg.get('battery_soc_percent'))
        if mode.startswith('battery_') and self.battery_soc_percent is None:
            self.battery_soc_percent = 50.0

        # Initialize with some random values
        self.total_energy_produced_kwh = 440.0
        self.total_energy_consumed_kwh = 390.0
        self.total_energy_fed_in_kwh = 240.0

        self.current_power_produced_kw = 3.0
        self.current_power_consumed_from_grid_kw = 0.0
        self.current_power_consumed_from_pv_kw = 1.0
        self.current_power_consumed_total_kw = 1.0
        self.current_power_fed_in_kw = 2.0
        # Optional diagnostic values are simulated, not additional hardware data.
        self.pv_dc_power_kw = 3.0
        self.inverter_ac_power_kw = 2.85
        self.pv_mppt_power_kw = [1.5, 1.5]
        self.battery_power_kw = 0.0
        self.battery_mode = 'normal' if self.battery_soc_percent is not None else None

    # Increment the values on each update, just so something changes
    def update(self):
        '''Increment the values on each update, just so something changes.'''
        self._tick += 1
        if self._fault_mode == 'offline':
            raise OSError('simulated device offline')
        if self._fault_mode == 'zero_daylight':
            self.current_power_produced_kw = 0.0
        elif self._fault_mode != 'stale':
            self.current_power_produced_kw = 3.0

        self._update_equipment()
        self._update_counters()
        self._update_battery_soc()

    def _update_equipment(self):
        if self._fault_mode != 'stale':
            self.pv_dc_power_kw = self.current_power_produced_kw
            self.inverter_ac_power_kw = self.pv_dc_power_kw * 0.95
            self.pv_mppt_power_kw = [self.pv_dc_power_kw / 2] * 2
            self.battery_power_kw = 0.3 if self.battery_soc_percent is not None else 0.0
            self.battery_mode = 'normal' if self.battery_soc_percent is not None else None
        if self._fault_mode == 'inverter_dc_without_ac':
            self.inverter_ac_power_kw = 0.0
            self.battery_power_kw = 0.0
        elif self._fault_mode == 'panels_mppt_imbalance':
            self.pv_mppt_power_kw = [1.5, 0.05]
            self.pv_dc_power_kw = sum(self.pv_mppt_power_kw)
            self.current_power_produced_kw = self.pv_dc_power_kw
            self.inverter_ac_power_kw = self.pv_dc_power_kw * 0.95
        elif self._fault_mode == 'battery_fault':
            self.battery_mode = 'non operable (temperature)'
        elif self._fault_mode in ('battery_charge_stalled', 'battery_stuck'):
            self.battery_power_kw = 0.0 if self._fault_mode == 'battery_charge_stalled' else -1.0
        elif self._fault_mode == 'battery_soc_jump':
            # Keep power flowing so only the SOC rule is exercised, not charge_stalled.
            self.battery_power_kw = 0.3

        if self._fault_mode in ('zero_daylight', 'inverter_dc_without_ac'):
            # No AC output means no PV export and no PV self-consumption.
            self.current_power_fed_in_kw = 0.0
            self.current_power_consumed_from_pv_kw = 0.0
            self.current_power_consumed_from_grid_kw = self.current_power_consumed_total_kw

    def _update_counters(self):
        if self._fault_mode != 'stale':
            # Match main (+1 kWh per poll) unless a fault_mode is active.
            step = 1.0 if not self._fault_mode else 0.01
            if self._fault_mode == 'inverter_dc_without_ac':
                step = 0.0
            self.total_energy_produced_kwh = self.total_energy_produced_kwh + step
            self.total_energy_consumed_kwh = self.total_energy_consumed_kwh + step
            self.total_energy_fed_in_kwh = self.total_energy_fed_in_kwh + step

    def _update_battery_soc(self):
        if self.battery_soc_percent is not None:
            try:
                soc = float(self.battery_soc_percent)
            except (TypeError, ValueError):
                soc = None
            if self._fault_mode == 'battery_soc_jump':
                self.battery_soc_percent = 50.0 if self._tick % 2 else 70.0
            elif soc is not None and self._fault_mode not in ('battery_stuck', 'battery_charge_stalled'):
                soc = max(0.0, min(100.0, soc - 0.05))
                self.battery_soc_percent = soc
