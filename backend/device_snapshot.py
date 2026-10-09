'''Build a device-like snapshot for alert evaluation without a live read.'''


class DeviceSnapshot:
    def __init__(
            self,
            produced_kw=0.0,
            consumed_kw=0.0,
            fed_in_kw=0.0,
            total_produced_kwh=0.0,
            total_consumed_kwh=0.0,
            total_fed_in_kwh=0.0,
            battery_soc_percent=None):
        self.current_power_produced_kw = produced_kw
        self.current_power_consumed_from_grid_kw = 0.0
        self.current_power_consumed_from_pv_kw = 0.0
        self.current_power_consumed_total_kw = consumed_kw
        self.current_power_fed_in_kw = fed_in_kw
        self.total_energy_produced_kwh = total_produced_kwh
        self.total_energy_consumed_kwh = total_consumed_kwh
        self.total_energy_fed_in_kwh = total_fed_in_kwh
        self.battery_soc_percent = battery_soc_percent


def snapshot_from_db(db, live_device=None):
    '''Prefer live device counters; fill power from current table.'''
    produced_kw = 0.0
    consumed_kw = 0.0
    fed_in_kw = 0.0
    rows = db.execute("SELECT produced, consumed_total, fed_in FROM current "
                      "WHERE date='cur'")
    if rows:
        produced_kw = float(rows[0][0] or 0.0)
        consumed_kw = float(rows[0][1] or 0.0)
        fed_in_kw = float(rows[0][2] or 0.0)

    if live_device is not None:
        return DeviceSnapshot(
            produced_kw=getattr(
                live_device, 'current_power_produced_kw', produced_kw) or 0.0,
            consumed_kw=getattr(
                live_device, 'current_power_consumed_total_kw',
                consumed_kw) or 0.0,
            fed_in_kw=getattr(
                live_device, 'current_power_fed_in_kw', fed_in_kw) or 0.0,
            total_produced_kwh=float(getattr(
                live_device, 'total_energy_produced_kwh', 0.0) or 0.0),
            total_consumed_kwh=float(getattr(
                live_device, 'total_energy_consumed_kwh', 0.0) or 0.0),
            total_fed_in_kwh=float(getattr(
                live_device, 'total_energy_fed_in_kwh', 0.0) or 0.0),
            battery_soc_percent=getattr(
                live_device, 'battery_soc_percent', None),
        )

    from aggregates import all_time_row
    row = all_time_row(db)
    if row:
        return DeviceSnapshot(
            produced_kw=produced_kw,
            consumed_kw=consumed_kw,
            fed_in_kw=fed_in_kw,
            total_produced_kwh=float(row[2] or 0.0),
            total_consumed_kwh=float(row[4] or 0.0),
            total_fed_in_kwh=float(row[6] or 0.0),
            battery_soc_percent=None,
        )
    return DeviceSnapshot(
        produced_kw=produced_kw,
        consumed_kw=consumed_kw,
        fed_in_kw=fed_in_kw,
    )
