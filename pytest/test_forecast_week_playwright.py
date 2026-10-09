'''Playwright layout checks for the forecast week table on narrow viewports.'''

import socket
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

LANGS = (
    {
        "lang": "en",
        "prod": "Production",
        "prodShort": "Prod.",
        "cons": "Consumption",
        "consShort": "Cons.",
    },
    {
        "lang": "de",
        "prod": "Erzeugung",
        "prodShort": "Erz.",
        "cons": "Verbrauch",
        "consShort": "Verb.",
    },
    {
        "lang": "fr",
        "prod": "Production",
        "prodShort": "Prod.",
        "cons": "Consommation",
        "consShort": "Cons.",
    },
)

WIDTHS = (320, 360, 375, 414)


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def ui_server():
    port = _free_port()
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    httpd = ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{port}"
    httpd.shutdown()


@pytest.fixture(scope="module")
def playwright_browser():
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip(
            "playwright not installed; pip install -r requirements-dev.txt")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            pytest.skip(
                "Playwright Chromium browser missing; run "
                "'python -m playwright install chromium' "
                f"({type(exc).__name__})")
        yield browser
        browser.close()


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("labels", LANGS, ids=["en", "de", "fr"])
def test_forecast_week_table_fits_wrapper(
        ui_server, playwright_browser, width, labels):
    page = playwright_browser.new_page(
        viewport={"width": width, "height": 800})
    page.goto(
        ui_server + "/tests/ui/forecast_week_harness.html",
        wait_until="networkidle")
    page.evaluate(
        "(args) => window.setupForecastWeekTable(args[0], args[1])",
        [labels, 12345.7])
    fits = page.evaluate("window.tableFitsWrapper()")
    assert fits is True
    page.close()
