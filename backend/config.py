import yaml
import logging


class ConfigError(Exception):
    '''Raised when config.yml cannot be read or parsed.'''


class Config:
    def __init__(self, file_name):
        try:
            with open(file_name, "r", encoding="utf-8") as file:
                raw = yaml.safe_load(file)
            if raw is None or not isinstance(raw, dict):
                raise ConfigError(
                    f"{file_name} is empty or not a YAML mapping")
            self.config_data = raw
            try:
                self.load_settings(self.config_data)
            except KeyError as exc:
                key = exc.args[0] if exc.args else "unknown"
                raise ConfigError(
                    f"missing required key '{key}' in {file_name}") from exc
        except ConfigError:
            raise
        except Exception as e:
            raise ConfigError(
                f"Failed to load configuration from {file_name}: {e}") from e

    def load_settings(self, yaml_data):
        '''Copy settings from the yaml data for easier access.'''
        # Logging
        self.log_level = logging.INFO
        if self.config_data['logging'] == 'verbose':
            logging.info("Verbose logging is enabled")
            self.log_level = logging.DEBUG

        grabber = self.config_data.get('grabber')
        if not isinstance(grabber, dict):
            raise KeyError('grabber')
        if 'interval_s' not in grabber:
            raise KeyError('grabber.interval_s')

        self._instance_settings = self._resolve_instance_settings()
        self._validate_optional_features()

    def _validate_optional_features(self):
        from feature_settings import (
            alerts_settings,
            forecast_settings,
            notifications_settings,
        )
        data = self.config_data
        if 'forecast' in data:
            try:
                forecast_settings(data)
            except ConfigError as exc:
                logging.warning(
                    "Forecast configuration invalid; forecasting disabled: %s",
                    exc)
                block = data.get('forecast')
                if not isinstance(block, dict):
                    data['forecast'] = {'enabled': False}
                else:
                    block['enabled'] = False
        if 'alerts' in data:
            alerts_settings(data)
        if 'notifications' in data:
            notifications_settings(data)

    @staticmethod
    def _name_from_block(block):
        if block is None or not isinstance(block, dict):
            return None
        if 'name' not in block:
            return None
        name = block['name']
        if name is None:
            return None
        return str(name)

    def _resolve_instance_settings(self):
        data = self.config_data
        has_strata = 'stratasolar' in data
        has_legacy = 'sunalyzer' in data

        if has_strata and has_legacy:
            logging.warning(
                "Both 'stratasolar' and 'sunalyzer' config blocks are set; "
                "the legacy 'sunalyzer' block is only used if 'stratasolar' "
                "does not define a name")

        if has_legacy:
            logging.warning(
                "Config key 'sunalyzer' is deprecated; "
                "rename to 'stratasolar'")

        name = None
        if has_strata:
            name = self._name_from_block(data.get('stratasolar'))

        if name is None and has_legacy:
            legacy_name = self._name_from_block(data.get('sunalyzer'))
            if legacy_name is not None:
                name = legacy_name

        if name is None:
            name = ''

        return {'name': name}

    def instance_settings(self):
        '''General instance settings (display name, etc.).'''
        return self._instance_settings
