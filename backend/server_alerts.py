'''Grabber-stale alert evaluation (server background thread only).'''

import logging

from aggregates import grabber_loop_age_seconds
from alert_engine import _transition
from database import Database
from feature_settings import alerts_settings


def evaluate_grabber_stale_once(config):
    if config is None:
        return
    db = Database("data/db.sqlite")
    try:
        settings = alerts_settings(config.config_data)
        if not settings['enabled']:
            return
        interval_s = int(config.config_data['grabber']['interval_s'])
        stale_limit = max(
            settings['device_stale_min_s'],
            settings['device_stale_multiplier'] * interval_s)
        loop_age = grabber_loop_age_seconds(db)
        loop_stale = loop_age is None or loop_age > stale_limit
        _transition(
            db,
            'grabber_stale',
            loop_stale,
            'Data recording stalled',
            'The grabber loop heartbeat is older than expected.',
            {'loop_age_s': loop_age, 'limit_s': stale_limit},
            settings)
        db.connection.commit()
    except Exception:
        logging.exception("Server: grabber_stale evaluation failed")
    finally:
        db.close()
