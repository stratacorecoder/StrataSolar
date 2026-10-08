import yaml
import traceback
import logging


class Config:
    def __init__(self, file_name):
        try:
            with open(file_name, "r", encoding="utf-8") as file:
                self.config_data = yaml.safe_load(file)
                self.load_settings(self.config_data)
        except Exception as e:
            logging.error("Config error: "
                          "loading/parsing the configuration file failed")
            logging.error(e)
            traceback.print_exc()
            exit()

    def load_settings(self, yaml_data):
        '''Copy settings from the yaml data for easier access.'''
        # Logging
        self.log_level = logging.INFO
        if self.config_data['logging'] == 'verbose':
            logging.info("Verbose logging is enabled")
            self.log_level = logging.DEBUG

        self._instance_settings = self._resolve_instance_settings()

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
