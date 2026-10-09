'''Grabber SIGTERM handler must not deadlock when locks are held.'''

import signal
import threading
import time

import background_worker as bg
import grabber


def test_sigterm_handler_returns_while_event_lock_held():
    '''Reproduces r11 sigdl_wait: old handler blocked on Event.set().'''
    grabber.run = True
    done = threading.Event()

    def invoke():
        with grabber._grabber_wake._cond:
            grabber.handler_stop_signals(signal.SIGTERM, None)
            done.set()

    thread = threading.Thread(target=invoke)
    thread.start()
    assert done.wait(timeout=3.0)
    thread.join(timeout=3.0)
    assert not thread.is_alive()
    assert grabber.run is False


def test_sigterm_handler_returns_while_queue_lock_held():
    '''Reproduces r11 sigdl_enqueue: old handler blocked on queue.put().'''
    grabber.run = True
    done = threading.Event()

    def invoke():
        with bg._queue.mutex:
            grabber.handler_stop_signals(signal.SIGTERM, None)
            done.set()

    thread = threading.Thread(target=invoke)
    thread.start()
    assert done.wait(timeout=3.0)
    thread.join(timeout=3.0)
    assert not thread.is_alive()
    assert grabber.run is False


def test_sigterm_during_event_wait_wakes_main_loop():
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1] / "backend"
    script = """
import os
import signal
import sys
import threading
import time

import grabber

grabber.run = True
signal.signal(signal.SIGTERM, grabber.handler_stop_signals)

def send_term():
    time.sleep(0.25)
    os.kill(os.getpid(), signal.SIGTERM)

threading.Thread(target=send_term, daemon=True).start()
t0 = time.monotonic()
grabber._grabber_wake.wait(timeout=30.0)
elapsed = time.monotonic() - t0
ok = (not grabber.run) and elapsed < 5.0
sys.exit(0 if ok else 1)
"""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(backend)
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        env=env,
    )
    try:
        proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=3)
        raise AssertionError("grabber did not exit SIGTERM during Event.wait")
    assert proc.returncode == 0
