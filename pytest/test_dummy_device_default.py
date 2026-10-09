from devices.Dummy import Dummy


def test_default_increment_matches_main():
    dev = Dummy(None)
    before = dev.total_energy_produced_kwh
    dev.update()
    assert dev.total_energy_produced_kwh == before + 1.0


def test_fault_mode_uses_smaller_increment():
    class _Cfg:
        config_data = {"dummy": {"fault_mode": "zero_daylight"}}
    dev = Dummy(_Cfg())
    before = dev.total_energy_produced_kwh
    dev.update()
    assert dev.total_energy_produced_kwh == before + 0.01
