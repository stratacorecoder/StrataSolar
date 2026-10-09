'''Background network I/O (forecast refresh, notifications).'''

import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

_JOB_FORECAST = 'forecast_refresh'
_JOB_NOTIFICATIONS = 'notifications'

_queue = queue.Queue()
_thread = None
_stop = threading.Event()
_config = None
_tz = None
_forecast_backoff_until = 0.0


def start_background_worker(config, tz):
    global _config, _tz, _thread
    _config = config
    _tz = tz
    if _thread is not None and _thread.is_alive():
        return
    _stop.clear()
    _thread = threading.Thread(
        target=_worker_loop, name='stratasolar-bg', daemon=True)
    _thread.start()


def stop_background_worker():
    _stop.set()


def enqueue_forecast_refresh():
    _queue.put((_JOB_FORECAST, None))


def enqueue_notification_flush():
    _queue.put((_JOB_NOTIFICATIONS, None))


def _worker_loop():
    while not _stop.is_set():
        try:
            job, _payload = _queue.get(timeout=1.0)
        except queue.Empty:
            continue
        try:
            if job == _JOB_FORECAST:
                _run_forecast_job()
            elif job == _JOB_NOTIFICATIONS:
                _run_notifications_job()
        except Exception:
            logging.exception("Background worker job failed: %s", job)


def _run_forecast_job():
    global _forecast_backoff_until
    if _config is None or _tz is None:
        return
    if time.monotonic() < _forecast_backoff_until:
        return
    from forecast_service import run_forecast_refresh_background
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(run_forecast_refresh_background, _config, _tz)
        try:
            ok = fut.result(timeout=25.0)
        except FutTimeout:
            logging.warning("Forecast background refresh timed out")
            ok = False
    if not ok:
        _forecast_backoff_until = time.monotonic() + 300.0
    else:
        _forecast_backoff_until = 0.0


def _run_notifications_job():
    if _config is None:
        return
    from notifications import process_outbox_once
    with ThreadPoolExecutor(max_workers=1) as pool:
        fut = pool.submit(process_outbox_once, _config)
        try:
            fut.result(timeout=20.0)
        except FutTimeout:
            logging.warning("Notification flush timed out")
