import logging
from pathlib import Path

from config import Config

_BASE_CONFIG = """
logging: normal
time_zone: Europe/Berlin
device:
  type: Dummy
  start_date: 2020-01-01
prices:
  price_per_grid_kwh: 0.1
  revenue_per_fed_in_kwh: 0.1
server:
  ip: 0.0.0.0
  port: 5000
grabber:
  interval_s: 5
"""


def _write_config(tmp_path: Path, extra: str) -> str:
    path = tmp_path / "config.yml"
    path.write_text(_BASE_CONFIG + extra, encoding="utf-8")
    return str(path)


def test_instance_settings_stratasolar_name(tmp_path):
    path = _write_config(tmp_path, '\nstratasolar:\n  name: "New Site"\n')
    cfg = Config(path)
    assert cfg.instance_settings() == {"name": "New Site"}


def test_instance_settings_legacy_sunalyzer(tmp_path, caplog):
    path = _write_config(tmp_path, '\nsunalyzer:\n  name: "Old Site"\n')
    with caplog.at_level(logging.WARNING):
        cfg = Config(path)
    assert cfg.instance_settings() == {"name": "Old Site"}
    assert any("deprecated" in r.message for r in caplog.records)
    caplog.clear()
    assert cfg.instance_settings() == {"name": "Old Site"}
    assert not caplog.records


def test_instance_settings_neither_key_defaults_empty_name(tmp_path):
    path = _write_config(tmp_path, "")
    cfg = Config(path)
    assert cfg.instance_settings() == {"name": ""}


def test_instance_settings_empty_stratasolar_falls_back_to_legacy(
        tmp_path, caplog):
    path = _write_config(
        tmp_path,
        '\nstratasolar:\n\nsunalyzer:\n  name: "Legacy Site"\n')
    with caplog.at_level(logging.WARNING):
        cfg = Config(path)
    assert cfg.instance_settings() == {"name": "Legacy Site"}
    assert any("deprecated" in r.message for r in caplog.records)


def test_instance_settings_both_keys_stratasolar_wins(tmp_path, caplog):
    path = _write_config(
        tmp_path,
        '\nstratasolar:\n  name: "Primary"\n'
        'sunalyzer:\n  name: "Ignored"\n')
    with caplog.at_level(logging.WARNING):
        cfg = Config(path)
    assert cfg.instance_settings() == {"name": "Primary"}
    assert any(
        "Both 'stratasolar' and 'sunalyzer'" in r.message
        for r in caplog.records)


def test_instance_settings_stratasolar_without_name_falls_back(
        tmp_path, caplog):
    path = _write_config(
        tmp_path,
        '\nstratasolar: {}\nsunalyzer:\n  name: "From Legacy"\n')
    with caplog.at_level(logging.WARNING):
        cfg = Config(path)
    assert cfg.instance_settings() == {"name": "From Legacy"}
