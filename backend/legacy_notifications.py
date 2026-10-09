'''Warn when outbound notification settings are present but unsupported.'''

import logging
import os


def warn_ignored_outbound_notifications(config_data):
    if config_data is None:
        config_data = {}
    block = config_data.get('notifications')
    if isinstance(block, dict) and block:
        logging.warning(
            "Outbound notifications are not supported in this version; "
            "notifications: settings are ignored.")
    if os.environ.get('STRATASOLAR_WEBHOOK_URL', '').strip():
        logging.warning(
            "Outbound notifications are not supported in this version; "
            "STRATASOLAR_WEBHOOK_URL is ignored.")
    for env_key, value in os.environ.items():
        if not value or not str(value).strip():
            continue
        upper = env_key.upper()
        if upper.startswith('SMTP_') or upper.startswith('STRATASOLAR_SMTP_'):
            logging.warning(
                "Outbound notifications are not supported in this version; "
                "%s is ignored.", env_key)
            break
