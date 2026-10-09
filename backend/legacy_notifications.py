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
    for env_key in (
            'STRATASOLAR_SMTP_PASSWORD',
            'SMTP_PASSWORD',
            'SMTP_PASS'):
        if os.environ.get(env_key, '').strip():
            logging.warning(
                "Outbound notifications are not supported in this version; "
                "%s is ignored.", env_key)
            break
