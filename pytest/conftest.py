import os
import time

import pytest


@pytest.fixture
def restore_process_tz():
    '''Restore TZ and libc zone after tests that call tzset().'''
    original = os.environ.get("TZ")
    yield
    if original is None:
        os.environ.pop("TZ", None)
    else:
        os.environ["TZ"] = original
    time.tzset()


@pytest.fixture
def fast_grabber_counter_recorder():
    '''Use short reset confirmation in tests that call insert_historical_values.'''
    import grabber as g

    class _Clock:
        def __init__(self):
            self.t = 1_000_000.0

        def advance(self, seconds):
            self.t += float(seconds)

        def now(self):
            return self.t

    clock = _Clock()
    g.init_counter_recorder({
        'interval_s': 5,
        'counter_reset_confirm_minutes': 0,
        'counter_reset_confirm_samples': 3,
        'max_power_kw': 5000,
    }, clock=clock.now)
    g._test_counter_clock = clock
    yield
    g._counter_recorder = None
    g._test_counter_clock = None
