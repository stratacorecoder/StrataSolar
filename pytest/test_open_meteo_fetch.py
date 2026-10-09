'''Open-Meteo HTTP deadline, compression, single-flight, and retry behaviour.'''

import gzip
import json
import os
import subprocess
import sys
import threading
import time
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import background_worker as bg
import forecast_service as fs
import pytest

_JSON_BODY = (
    b'{"hourly":{"time":["2026-01-01T00:00"],'
    b'"global_tilted_irradiance":[100]}}'
)


class _DelayBodyHandler(BaseHTTPRequestHandler):
    delay_s = 0.0
    drip_interval_s = 0.0
    body = _JSON_BODY
    content_encoding = None

    def do_GET(self):
        if self.delay_s:
            time.sleep(self.delay_s)
        payload = self.body
        if self.content_encoding == "gzip":
            payload = gzip.compress(payload)
        elif self.content_encoding == "deflate":
            payload = zlib.compress(payload)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        if self.content_encoding:
            self.send_header("Content-Encoding", self.content_encoding)
        self.end_headers()
        if self.drip_interval_s > 0:
            for i in range(0, len(payload)):
                self.wfile.write(payload[i:i + 1])
                self.wfile.flush()
                time.sleep(self.drip_interval_s)
        else:
            self.wfile.write(payload)

    def log_message(self, *_args):
        return


def _run_server(handler_cls):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler_cls)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port, thread


def _fetch_local(port, delay_s=0.0, drip=0.0, deadline_s=15.0, encoding=None):
    _DelayBodyHandler.delay_s = delay_s
    _DelayBodyHandler.drip_interval_s = drip
    _DelayBodyHandler.content_encoding = encoding
    url = f"http://127.0.0.1:{port}/"
    deadline = fs.MeteoDeadline(deadline_s)
    return fs._fetch_open_meteo(url, {}, deadline)


def test_slow_responses_within_deadline_succeed():
    server, port, _thr = _run_server(_DelayBodyHandler)
    try:
        for delay in (2.0, 3.0):
            data = _fetch_local(port, delay_s=delay, deadline_s=15.0)
            assert data is not None
            assert "hourly" in data
        data = _fetch_local(port, delay_s=5.0, deadline_s=15.0)
        assert data is not None
        data = _fetch_local(port, delay_s=10.0, deadline_s=16.0)
        assert data is not None
    finally:
        server.shutdown()


@pytest.mark.parametrize("encoding", ["gzip", "deflate"])
def test_compressed_response_decodes(encoding):
    server, port, _thr = _run_server(_DelayBodyHandler)
    try:
        data = _fetch_local(port, encoding=encoding, deadline_s=10.0)
        assert data is not None
        assert data["hourly"]["global_tilted_irradiance"][0] == 100
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


def test_single_flight_blocks_overlapping_refresh(monkeypatch):
    bg.stop_background_worker()
    bg._thread = None
    bg._forecast_failures = 0
    bg._forecast_backoff_until = 0.0
    bg._forecast_busy = False
    started = threading.Event()
    release = threading.Event()
    concurrent = []

    def slow_refresh(_config, _tz):
        started.set()
        concurrent.append(1)
        release.wait(timeout=30)
        concurrent.pop()
        return False

    monkeypatch.setattr(
        "forecast_service.run_forecast_refresh_background", slow_refresh)
    bg._config = object()
    bg._tz = "UTC"
    bg._stop.clear()
    bg.start_background_worker(bg._config, bg._tz)
    bg.enqueue_forecast_refresh()
    assert started.wait(timeout=3.0)
    time.sleep(0.1)
    bg._run_forecast_job()
    assert len(concurrent) == 1
    assert bg.forecast_fetch_busy()
    release.set()
    time.sleep(0.4)
    assert not bg.forecast_fetch_busy()
    bg.stop_background_worker()


def test_drip_cycles_do_not_grow_thread_count():
    server, port, _thr = _run_server(_DelayBodyHandler)
    try:
        baseline = threading.active_count()
        for _ in range(6):
            _fetch_local(port, drip=0.15, deadline_s=3.0)
        assert threading.active_count() <= baseline + 2
    finally:
        server.shutdown()


def test_fetch_exception_is_logged_not_raised(caplog):
    server, port, _thr = _run_server(_DelayBodyHandler)
    try:
        with patch.object(
                fs, "_read_response_body",
                side_effect=RuntimeError("boom")):
            with caplog.at_level("ERROR"):
                assert _fetch_local(port, deadline_s=5.0) is None
            assert "Open-Meteo request failed" in caplog.text
    finally:
        server.shutdown()


def test_retry_backoff_from_finish_time(monkeypatch):
    bg._forecast_failures = 0
    bg._forecast_backoff_until = 0.0
    bg._last_forecast_finish_mono = 0.0
    t0 = time.monotonic()

    def slow_fail(_config, _tz):
        time.sleep(0.05)
        return False

    monkeypatch.setattr(
        "forecast_service.run_forecast_refresh_background", slow_fail)
    bg._config = object()
    bg._tz = "UTC"
    bg._stop.clear()
    bg.start_background_worker(bg._config, bg._tz)
    bg.enqueue_forecast_refresh()
    for _ in range(50):
        if bg._last_forecast_finish_mono > 0:
            break
        time.sleep(0.02)
    finish = bg._last_forecast_finish_mono
    assert finish >= t0
    assert bg.forecast_backoff_until_mono() == finish + 120.0
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


@pytest.mark.skipif(
    os.environ.get("STRATASOLAR_OPEN_METEO_LIVE") != "1",
    reason="set STRATASOLAR_OPEN_METEO_LIVE=1 for live Open-Meteo smoke test",
)
def test_live_open_meteo_smoke():
    deadline = fs.MeteoDeadline(20)
    data = fs._fetch_open_meteo(
        "https://api.open-meteo.com/v1/forecast",
        {
            "latitude": 14.6,
            "longitude": 121.0,
            "hourly": "temperature_2m",
            "forecast_days": 1,
        },
        deadline,
    )
    assert data is not None
    assert "hourly" in data
