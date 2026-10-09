'''Background network I/O (forecast refresh).'''

import logging
import queue
import threading
import time

_JOB_FORECAST = 'forecast_refresh'
_WAKE = None

_queue = queue.Queue()
_thread = None
_stop = threading.Event()
_config = None
_tz = None
_forecast_backoff_until = 0.0
_forecast_failures = 0
_last_forecast_finish_mono = 0.0
_forecast_lock = threading.Lock()
_forecast_busy = False
_forecast_pending = False
_refresh_owner = None

_STOP_JOIN_S = 1.0
_RETRY_DELAYS_S = (120.0, 300.0, 900.0, 1800.0)


def start_background_worker(config, tz):
    global _config, _tz, _thread, _forecast_pending
    _config = config
    _tz = tz
    if _thread is not None and _thread.is_alive():
        if not _stop.is_set():
            return
        _thread.join(timeout=_STOP_JOIN_S)
        if _thread.is_alive():
            return
    _stop.clear()
    with _forecast_lock:
        _forecast_pending = False
    _thread = threading.Thread(
        target=_worker_loop, name='stratasolar-bg', daemon=True)
    _thread.start()


def stop_background_worker():
    request_worker_stop()
    if _thread is not None and _thread.is_alive():
        _thread.join(timeout=_STOP_JOIN_S)


def forecast_retry_interval_s(normal_refresh_s):
    '''Seconds until the next refresh may be scheduled after failures.'''
    if _forecast_failures == 0:
        return float(normal_refresh_s)
    idx = min(_forecast_failures - 1, len(_RETRY_DELAYS_S) - 1)
    return _RETRY_DELAYS_S[idx]


def forecast_backoff_until_mono():
    return _forecast_backoff_until


def forecast_last_finish_mono():
    return _last_forecast_finish_mono


def forecast_fetch_busy():
    with _forecast_lock:
        return _forecast_busy


def forecast_refresh_in_flight():
    with _forecast_lock:
        return _forecast_busy or _forecast_pending


def request_worker_stop():
    _stop.set()
    try:
        _queue.put((_WAKE, None), block=False)
    except queue.Full:
        pass


def enqueue_forecast_refresh():
    global _forecast_pending
    with _forecast_lock:
        if _forecast_busy or _forecast_pending:
            return
        _forecast_pending = True
        _queue.put((_JOB_FORECAST, None))


def _worker_loop():
    global _forecast_busy, _forecast_pending, _refresh_owner
    while not _stop.is_set():
        try:
            job, _payload = _queue.get(timeout=1.0)
        except queue.Empty:
            continue
        if job is _WAKE:
            continue
        if job != _JOB_FORECAST:
            continue
        with _forecast_lock:
            _forecast_pending = False
            _forecast_busy = True
            _refresh_owner = threading.get_ident()
        try:
            _run_forecast_job()
        except Exception:
            logging.exception("Background worker job failed: %s", job)


def _record_forecast_result(weather_ok):
    global _forecast_failures, _forecast_backoff_until
    global _last_forecast_finish_mono
    now = time.monotonic()
    _last_forecast_finish_mono = now
    if weather_ok:
        _forecast_failures = 0
        _forecast_backoff_until = 0.0
        return
    _forecast_failures += 1
    idx = min(_forecast_failures - 1, len(_RETRY_DELAYS_S) - 1)
    _forecast_backoff_until = now + _RETRY_DELAYS_S[idx]


def _run_forecast_job():
    global _forecast_busy, _refresh_owner
    with _forecast_lock:
        if threading.get_ident() != _refresh_owner:
            return
    if _config is None or _tz is None or _stop.is_set():
        with _forecast_lock:
            _forecast_busy = False
            _refresh_owner = None
        return
    if time.monotonic() < _forecast_backoff_until:
        with _forecast_lock:
            _forecast_busy = False
            _refresh_owner = None
        return
    weather_ok = False
    try:
        from forecast_service import run_forecast_refresh_background
        weather_ok = bool(run_forecast_refresh_background(_config, _tz))
    except Exception:
        logging.exception("Forecast background refresh failed")
    finally:
        _record_forecast_result(weather_ok)
        with _forecast_lock:
            _forecast_busy = False
            _refresh_owner = None
