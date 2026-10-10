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
    bg._forecast_busy = False
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


def test_restart_during_fetch_runs_next_five_refreshes():
    backend = Path(__file__).resolve().parents[1] / "backend"
    script = textwrap.dedent("""
        import threading
        import time
        import background_worker as bw
        import forecast_service as fs

        started = threading.Event()
        calls = 0
        calls_lock = threading.Lock()

        def refresh(_config, _tz):
            global calls
            with calls_lock:
                calls += 1
                call_number = calls
            if call_number == 1:
                started.set()
                time.sleep(3.5)
            return True

        def wait_until_idle(expected_calls):
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                with calls_lock:
                    done = calls >= expected_calls
                if done and not bw.forecast_refresh_in_flight():
                    return
                time.sleep(0.01)
            raise AssertionError("refresh did not finish")

        def alive_workers():
            return [thread for thread in threading.enumerate()
                    if thread.name == "stratasolar-bg" and thread.is_alive()]

        fs.run_forecast_refresh_background = refresh
        config = object()
        bw.start_background_worker(config, "UTC")
        bw.enqueue_forecast_refresh()
        assert started.wait(timeout=3)

        bw.request_worker_stop()
        bw.start_background_worker(config, "UTC")
        assert not bw._stop.is_set()
        assert len(alive_workers()) <= 1

        wait_until_idle(1)
        for expected_calls in range(2, 7):
            bw.enqueue_forecast_refresh()
            wait_until_idle(expected_calls)
            assert len(alive_workers()) <= 1

        with calls_lock:
            assert calls == 6
        assert not bw._forecast_pending
        assert not bw.forecast_refresh_in_flight()

        # Queue a refresh immediately before stop while the worker is blocked
        # on the lifecycle lock. It must put that job back before exiting.
        with bw._lifecycle_lock:
            bw.enqueue_forecast_refresh()
            bw._request_worker_stop_locked()
        deadline = time.monotonic() + 3
        while bw._exiting_thread is not bw._thread:
            if time.monotonic() >= deadline:
                raise AssertionError("worker did not commit to exit")
            time.sleep(0.01)
        assert bw._forecast_pending
        bw.start_background_worker(config, "UTC")
        wait_until_idle(7)
        with calls_lock:
            assert calls == 7
        assert not bw._forecast_pending
        assert len(alive_workers()) <= 1

        bw.stop_background_worker()
        assert not alive_workers()
    """)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend)
    subprocess.run(
        [sys.executable, "-c", script], env=env, check=True, timeout=20)


def test_one_hundred_concurrent_worker_starts_do_not_lose_job():
    backend = Path(__file__).resolve().parents[1] / "backend"
    script = textwrap.dedent("""
        import threading
        import time
        import background_worker as bw
        import forecast_service as fs

        calls = 0
        calls_lock = threading.Lock()
        ran = threading.Event()
        start_barrier = threading.Barrier(101)
        errors = []

        def refresh(_config, _tz):
            global calls
            with calls_lock:
                calls += 1
            ran.set()
            return True

        def start_worker():
            try:
                start_barrier.wait(timeout=5)
                bw.start_background_worker(object(), "UTC")
            except Exception as exc:
                errors.append(exc)

        def alive_workers():
            return [thread for thread in threading.enumerate()
                    if thread.name == "stratasolar-bg" and thread.is_alive()]

        fs.run_forecast_refresh_background = refresh
        bw.enqueue_forecast_refresh()
        starters = [threading.Thread(target=start_worker) for _ in range(100)]
        for thread in starters:
            thread.start()
        start_barrier.wait(timeout=5)
        for thread in starters:
            thread.join(timeout=5)
            assert not thread.is_alive()

        assert not errors
        assert ran.wait(timeout=5)
        deadline = time.monotonic() + 5
        while bw.forecast_refresh_in_flight() and time.monotonic() < deadline:
            time.sleep(0.01)
        with calls_lock:
            assert calls == 1
        assert not bw._forecast_pending
        assert len(alive_workers()) <= 1
        bw.stop_background_worker()
        assert not alive_workers()
    """)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend)
    subprocess.run(
        [sys.executable, "-c", script], env=env, check=True, timeout=15)
