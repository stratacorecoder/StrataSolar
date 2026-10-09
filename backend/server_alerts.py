'''Throttled alert evaluation from the web server (grabber may be dead).'''

import logging
import time

from aggregates import grabber_loop_age_seconds
from alert_engine import _transition
from database import Database
from feature_settings import alerts_settings
_last_server_eval_mono = 0.0
_SERVER_EVAL_INTERVAL_S = 30.0


def maybe_evaluate_alerts_from_server(config):
    global _last_server_eval_mono
    if config is None:
        return
    now = time.monotonic()
    if now - _last_server_eval_mono < _SERVER_EVAL_INTERVAL_S:
        return
    _last_server_eval_mono = now
    db = Database("data/db.sqlite")
    try:
        settings = alerts_settings(config.config_data)
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
        logging.exception("Server: alert evaluation failed")
    finally:
        db.close()
