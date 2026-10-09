'''Background tasks for the web server (no GET handler writes).'''

import logging
import threading
import time

_stop = threading.Event()
_thread = None
_config = None


def start_server_background(config):
    global _config, _thread
    _config = config
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(
        target=_loop, name='stratasolar-server-bg', daemon=True)
    _thread.start()


def stop_server_background():
    _stop.set()


def _loop():
    while not _stop.is_set():
        if _config is not None:
            try:
                from background_worker import enqueue_notification_flush
                from server_alerts import evaluate_grabber_stale_once

                evaluate_grabber_stale_once(_config)
                enqueue_notification_flush()
            except Exception:
                logging.exception(
                    "Server background: grabber_stale check failed")
        time.sleep(30.0)
