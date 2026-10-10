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
_lifecycle_lock = threading.Lock()
_exiting_thread = None
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
    global _config, _tz, _thread
    with _lifecycle_lock:
        _config = config
        _tz = tz
        if _thread is not None and _thread.is_alive():
            if _exiting_thread is not _thread:
                # Running, or stopped but still finishing a fetch: revive it.
                # It re-checks _stop under _lifecycle_lock before exiting, so
                # there is never a second worker and no queued job is lost.
                _stop.clear()
                return
            # This thread has committed to exit and will not acquire the
            # lifecycle lock again. Wait for it before publishing a new one.
            _thread.join()
        _stop.clear()
        _thread = threading.Thread(
            target=_worker_loop, name='stratasolar-bg', daemon=True)
        _thread.start()


def _request_worker_stop_locked():
    _stop.set()
    try:
        _queue.put((_WAKE, None), block=False)
    except queue.Full:
        pass


def _worker_mark_exiting_locked():
    global _exiting_thread
    _exiting_thread = threading.current_thread()


def stop_background_worker():
    with _lifecycle_lock:
        _request_worker_stop_locked()
        thread = _thread
    if thread is not None and thread.is_alive():
        thread.join(timeout=_STOP_JOIN_S)


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
    with _lifecycle_lock:
        _request_worker_stop_locked()


def enqueue_forecast_refresh():
    global _forecast_pending
    with _forecast_lock:
        if _forecast_busy or _forecast_pending:
            return
        _forecast_pending = True
        _queue.put((_JOB_FORECAST, None))


def _worker_loop():
    global _forecast_busy, _forecast_pending, _refresh_owner
    while True:
        try:
            job, _payload = _queue.get(timeout=1.0)
        except queue.Empty:
            with _lifecycle_lock:
                if _stop.is_set():
                    _worker_mark_exiting_locked()
                    return
            continue
        with _lifecycle_lock:
            if _stop.is_set():
                if job == _JOB_FORECAST:
                    # Keep the pending flag and restore the job for the next
                    # worker. A stopping worker must not consume a refresh.
                    _queue.put((job, _payload))
                _worker_mark_exiting_locked()
                return
            if job is _WAKE or job != _JOB_FORECAST:
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
    global _forecast_busy, _forecast_pending, _refresh_owner
    with _forecast_lock:
        if threading.get_ident() != _refresh_owner:
            return
    if _config is None or _tz is None:
        with _forecast_lock:
            _forecast_busy = False
            _refresh_owner = None
        return
    with _lifecycle_lock:
        if _stop.is_set():
            with _forecast_lock:
                _forecast_busy = False
                _forecast_pending = True
                _refresh_owner = None
            _queue.put((_JOB_FORECAST, None))
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
