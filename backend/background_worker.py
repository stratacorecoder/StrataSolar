'''Background network I/O (forecast refresh).'''

import logging
import queue
import threading
import time

_JOB_FORECAST = 'forecast_refresh'

_queue = queue.Queue()
_thread = None
_stop = threading.Event()
_config = None
_tz = None
_forecast_backoff_until = 0.0
_forecast_lock = threading.Lock()
_active_forecast_thread = None

_FORECAST_JOB_WAIT_S = 7.0
_STOP_JOIN_S = 2.0


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
    with _forecast_lock:
        active = _active_forecast_thread
    if active is not None and active.is_alive():
        active.join(timeout=_STOP_JOIN_S)


def enqueue_forecast_refresh():
    _queue.put((_JOB_FORECAST, None))


def _worker_loop():
    while not _stop.is_set():
        try:
            job, _payload = _queue.get(timeout=1.0)
        except queue.Empty:
            continue
        if job != _JOB_FORECAST:
            continue
        try:
            _run_forecast_job()
        except Exception:
            logging.exception("Background worker job failed: %s", job)


def _run_forecast_job():
    global _forecast_backoff_until, _active_forecast_thread
    if _config is None or _tz is None or _stop.is_set():
        return
    if time.monotonic() < _forecast_backoff_until:
        return

    outcome = {'ok': False}

    def _work():
        try:
            from forecast_service import run_forecast_refresh_background
            outcome['ok'] = bool(
                run_forecast_refresh_background(_config, _tz))
        except Exception:
            logging.exception("Forecast background refresh failed")
            outcome['ok'] = False

    worker = threading.Thread(
        target=_work, name='stratasolar-forecast-fetch', daemon=True)
    with _forecast_lock:
        _active_forecast_thread = worker
    worker.start()
    worker.join(timeout=_FORECAST_JOB_WAIT_S)
    if worker.is_alive():
        logging.warning(
            "Forecast background refresh exceeded %ss deadline",
            _FORECAST_JOB_WAIT_S)
        ok = False
    else:
        ok = outcome['ok']
    with _forecast_lock:
        if _active_forecast_thread is worker:
            _active_forecast_thread = None
    if not ok:
        _forecast_backoff_until = time.monotonic() + 300.0
    else:
        _forecast_backoff_until = 0.0
