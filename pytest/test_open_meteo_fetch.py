'''Open-Meteo HTTP deadline, single-flight, and retry behaviour.'''

import json
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import background_worker as bg
import forecast_service as fs


class _DelayBodyHandler(BaseHTTPRequestHandler):
    delay_s = 0.0
    drip_interval_s = 0.0
    body = b'{"hourly":{"time":["2026-01-01T00:00"],"global_tilted_irradiance":[100]}}'

    def do_GET(self):
        if self.delay_s:
            time.sleep(self.delay_s)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if self.drip_interval_s > 0:
            for i in range(0, len(self.body), 1):
                self.wfile.write(self.body[i:i + 1])
                self.wfile.flush()
                time.sleep(self.drip_interval_s)
        else:
            self.wfile.write(self.body)

    def log_message(self, *_args):
        return


def _run_server(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, thread


def _fetch_local(port, delay_s=0.0, drip=0.0, deadline_s=10.0):
    _DelayBodyHandler.delay_s = delay_s
    _DelayBodyHandler.drip_interval_s = drip
    url = f"http://127.0.0.1:{port}/"
    deadline = fs.MeteoDeadline(deadline_s)
    return fs._fetch_open_meteo(url, {}, deadline)


def test_slow_responses_within_deadline_succeed():
    server, port, _thr = _run_server(_DelayBodyHandler)
    try:
        for delay in (2.0, 3.0, 5.0):
            data = _fetch_local(port, delay_s=delay, deadline_s=10.0)
            assert data is not None
            assert "hourly" in data
    finally:
        server.shutdown()


def test_drip_body_aborts_at_deadline():
    server, port, _thr = _run_server(_DelayBodyHandler)
    try:
        t0 = time.monotonic()
        data = _fetch_local(port, drip=0.5, deadline_s=4.0)
        elapsed = time.monotonic() - t0
        assert data is None
        assert elapsed < 6.5
        assert elapsed >= 3.0
    finally:
        server.shutdown()


def test_hanging_headers_abort():
    class _HangHandler(BaseHTTPRequestHandler):
        def do_GET(self):
            time.sleep(120)

        def log_message(self, *_args):
            return

    server, port, _thr = _run_server(_HangHandler)
    try:
        t0 = time.monotonic()
        data = _fetch_local(port, deadline_s=4.0)
        elapsed = time.monotonic() - t0
        assert data is None
        assert elapsed < 6.5
    finally:
        server.shutdown()


def test_single_flight_no_thread_growth(monkeypatch):
    bg._forecast_failures = 0
    bg._forecast_backoff_until = 0.0
    bg._active_forecast_thread = None
    started = threading.Event()
    release = threading.Event()

    def slow_refresh(_config, _tz):
        started.set()
        release.wait(timeout=30)
        return False

    monkeypatch.setattr(
        "forecast_service.run_forecast_refresh_background", slow_refresh)
    bg._config = object()
    bg._tz = "UTC"
    bg._stop.clear()
    bg.start_background_worker(bg._config, bg._tz)
    bg.enqueue_forecast_refresh()
    bg.enqueue_forecast_refresh()
    assert started.wait(timeout=3.0)
    time.sleep(0.2)
    with bg._forecast_lock:
        assert bg._active_forecast_thread is not None
        assert bg._active_forecast_thread.is_alive()
    release.set()
    time.sleep(0.3)
    bg.stop_background_worker()


def test_retry_backoff_schedule():
    bg._forecast_failures = 0
    bg._record_forecast_result(False)
    assert bg.forecast_retry_interval_s(3600) == 120.0
    bg._record_forecast_result(False)
    assert bg.forecast_retry_interval_s(3600) == 300.0
    bg._record_forecast_result(False)
    assert bg.forecast_retry_interval_s(3600) == 900.0
    bg._record_forecast_result(False)
    assert bg.forecast_retry_interval_s(3600) == 1800.0
    bg._record_forecast_result(True)
    assert bg.forecast_retry_interval_s(3600) == 3600.0


def test_subprocess_sigterm_exits_within_3s_mid_fetch():
    server, port, _thr = _run_server(_DelayBodyHandler)
    _DelayBodyHandler.delay_s = 120.0
    backend = Path(__file__).resolve().parents[1] / "backend"
    script = f"""
import time
import background_worker as bw
import forecast_service as fs

def hang_refresh(config, tz):
    fs._fetch_open_meteo("http://127.0.0.1:{port}/", {{}}, fs.MeteoDeadline(15))
    return False

import forecast_service
forecast_service.run_forecast_refresh_background = hang_refresh
bw.start_background_worker(object(), "UTC")
bw.enqueue_forecast_refresh()
time.sleep(10)
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend)
    proc = subprocess.Popen([sys.executable, "-c", script], env=env)
    time.sleep(0.5)
    proc.terminate()
    try:
        proc.wait(timeout=3)
    finally:
        server.shutdown()
    assert proc.returncode is not None
