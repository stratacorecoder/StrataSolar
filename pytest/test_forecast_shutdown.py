'''Process must stop quickly while a forecast fetch is hanging.'''

import os
import subprocess
import sys
import textwrap
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from pathlib import Path

import background_worker as bg


class _HangHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        time.sleep(120)

    def log_message(self, *_args):
        return


def test_stop_background_worker_exits_within_3s_during_hang(monkeypatch):
    def hang_forecast(_config, _tz):
        time.sleep(60)
        return False

    monkeypatch.setattr(
        "forecast_service.run_forecast_refresh_background", hang_forecast)
    bg._config = object()
    bg._tz = "UTC"
    bg._stop.clear()
    bg._forecast_backoff_until = 0.0
    bg.enqueue_forecast_refresh()
    bg.start_background_worker(bg._config, bg._tz)
    time.sleep(0.15)
    t0 = time.monotonic()
    bg.stop_background_worker()
    assert time.monotonic() - t0 < 3.0


def test_subprocess_sigterm_during_hanging_open_meteo_fetch():
    server = ThreadingHTTPServer(("127.0.0.1", 0), _HangHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    backend = Path(__file__).resolve().parents[1] / "backend"
    script = textwrap.dedent(f"""
import time
import requests
import background_worker as bw
import forecast_service as fs

def hang_fetch(url, params, timeout_s):
    requests.get("http://127.0.0.1:{port}/slow", timeout=timeout_s)

def hang_refresh(config, tz):
    hang_fetch("http://127.0.0.1:{port}/slow", {{}}, 7)
    return False

fs.run_forecast_refresh_background = hang_refresh
bw.start_background_worker(object(), "UTC")
bw.enqueue_forecast_refresh()
time.sleep(30)
""")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend)
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        env=env,
    )
    time.sleep(0.6)
    proc.terminate()
    try:
        proc.wait(timeout=3)
    finally:
        server.shutdown()
    assert proc.returncode is not None
