'''Background network I/O (forecast refresh).'''

import logging
import queue
import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutTimeout

_JOB_FORECAST = 'forecast_refresh'

_queue = queue.Queue()
_thread = None
_stop = threading.Event()
_config = None
_tz = None
_forecast_backoff_until = 0.0
_pool = None


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
    global _pool
    _stop.set()
    if _pool is not None:
        _pool.shutdown(wait=False, cancel_futures=True)
        _pool = None


def _executor():
    global _pool
    if _pool is None:
        _pool = ThreadPoolExecutor(max_workers=1)
    return _pool


def _run_timed(fn, timeout_s, label):
    fut = _executor().submit(fn)
    try:
        return fut.result(timeout=timeout_s)
    except FutTimeout:
        logging.warning("%s timed out after %ss", label, timeout_s)
        return None


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
    global _forecast_backoff_until
    if _config is None or _tz is None:
        return
    if time.monotonic() < _forecast_backoff_until:
        return
    from forecast_service import run_forecast_refresh_background
    ok = _run_timed(
        lambda: run_forecast_refresh_background(_config, _tz),
        25.0,
        "Forecast background refresh")
    if ok is None:
        ok = False
    if not ok:
        _forecast_backoff_until = time.monotonic() + 300.0
    else:
        _forecast_backoff_until = 0.0
