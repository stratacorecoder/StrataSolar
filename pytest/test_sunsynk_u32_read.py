import pytest

import devices.Sunsynk as sunsynk_mod
from devices.Sunsynk import Sunsynk


class FakeConfig:
    def __init__(self):
        self.config_data = {'sunsynk': {'connection': 'solarman'}}


class AtomicU32Transport:
    def __init__(self, registers):
        self.registers = registers
        self.calls = []

    def describe(self):
        return "atomic-u32"

    def open(self):
        pass

    def close(self):
        pass

    def read_holding_registers(self, address, count):
        self.calls.append((address, count))
        return [self.registers[address + i] for i in range(count)]


def test_read_u32_uses_single_modbus_request(monkeypatch):
    registers = {
        96: 0xFFFF, 97: 1,
        81: 500, 82: 0,
        85: 2000, 86: 0,
        184: 60, 190: 0,
        186: 0, 187: 0, 172: 0, 178: 1000,
    }
    transport = AtomicU32Transport(registers)
    monkeypatch.setitem(
        sunsynk_mod._TRANSPORTS, 'solarman', lambda _cfg: transport)
    dev = Sunsynk(FakeConfig())
    assert dev.total_energy_produced_kwh == pytest.approx(13107.1)
    assert (96, 2) in transport.calls
    assert (81, 2) in transport.calls
    assert (85, 2) in transport.calls
    assert all(count == 2 for addr, count in transport.calls if addr in (81, 85, 96))
