import os
import time

import pytest


@pytest.fixture(scope='session')
def chromium_launch_options():
    '''Optional real-browser mode for macOS sandboxes that deny Mach IPC.'''
    if os.environ.get('STRATASOLAR_TEST_SINGLE_PROCESS') == '1':
        return {'args': ['--single-process']}
    return {}


def _chromium_scope(fixture_name, config):
    # Closing a browser context exits single-process Chromium. Use a fresh
    # real browser per case in that mode; normal CI retains module sharing.
    return 'function' if os.environ.get('STRATASOLAR_TEST_SINGLE_PROCESS') == '1' else 'module'


@pytest.fixture(scope=_chromium_scope)
def playwright_browser(chromium_launch_options):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        if os.environ.get('CI', '').lower() in ('1', 'true', 'yes'):
            raise
        pytest.skip('playwright not installed')
    with sync_playwright() as p:
        browser = p.chromium.launch(**chromium_launch_options)
        yield browser
        if browser.is_connected():
            browser.close()


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
