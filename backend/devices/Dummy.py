# Dummy device for testing purposes
class Dummy:
    def __init__(self, config):
        if config is None:
            dummy_cfg = {}
        else:
            dummy_cfg = config.config_data.get('dummy') or {}
        if not isinstance(dummy_cfg, dict):
            dummy_cfg = {}
        self._fault_mode = str(dummy_cfg.get('fault_mode', '')).lower()
        self._tick = 0
        self.battery_soc_percent = dummy_cfg.get('battery_soc_percent')

        # Initialize with some random values
        self.total_energy_produced_kwh = 440.0
        self.total_energy_consumed_kwh = 390.0
        self.total_energy_fed_in_kwh = 240.0

        self.current_power_produced_kw = 3.0
        self.current_power_consumed_from_grid_kw = 0.0
        self.current_power_consumed_from_pv_kw = 1.0
        self.current_power_consumed_total_kw = 1.0
        self.current_power_fed_in_kw = 2.0

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

        if self._fault_mode != 'stale':
            # Match main (+1 kWh per poll) unless a fault_mode is active.
            step = 1.0 if not self._fault_mode else 0.01
            self.total_energy_produced_kwh = self.total_energy_produced_kwh + step
            self.total_energy_consumed_kwh = self.total_energy_consumed_kwh + step
            self.total_energy_fed_in_kwh = self.total_energy_fed_in_kwh + step

        if self.battery_soc_percent is not None:
            try:
                soc = float(self.battery_soc_percent)
            except (TypeError, ValueError):
                soc = None
            if soc is not None and self._fault_mode != 'battery_stuck':
                soc = max(0.0, min(100.0, soc - 0.05))
                self.battery_soc_percent = soc
