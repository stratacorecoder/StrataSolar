from pathlib import Path

from config import Config
import logging

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_template_config_is_readable():
    cfg = Config(str(REPO_ROOT / "templates/config.yml"))
    assert cfg is not None
    assert cfg.log_level is logging.DEBUG
    assert cfg.config_data["time_zone"] == "Europe/Berlin"
    assert cfg.instance_settings()["name"] == "My Site"
