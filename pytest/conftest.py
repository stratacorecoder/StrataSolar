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
