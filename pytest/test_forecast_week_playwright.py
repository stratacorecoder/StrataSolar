'''Playwright layout checks for the forecast week table (real index.html).'''

import os
import socket
import subprocess
import threading
from datetime import date, timedelta
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
WIDTHS = (320, 360, 375, 414, 415, 430, 768)
LANG_SWITCH = {
    "en": "switchLanguageToEnglish",
    "de": "switchLanguageToGerman",
    "fr": "switchLanguageToFrench",
}


def _in_ci():
    return os.environ.get("CI", "").lower() in ("1", "true", "yes")


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _forecast_payload():
    today = date.today()
    days = []
    for offset in range(7):
        d = today + timedelta(days=offset)
        days.append({
            "date": d.isoformat(),
            "production_kwh": 12345.7,
            "consumption_kwh": 67890.1,
            "hourly_production_kwh": [0.0] * 24,
        })
    return {
        "state": "ok",
        "source": "history",
        "today": today.isoformat(),
        "today_forecast_kwh": 12.3,
        "today_actual": {"production_kwh": 5.0},
        "hourly_today_cumulative": [0.0] * 24,
        "days": days,
    }


@pytest.fixture(scope="module")
def ui_server():
    port = _free_port()
    handler = partial(SimpleHTTPRequestHandler, directory=str(SITE))
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
        if _in_ci():
            raise
        pytest.skip(
            "playwright not installed; pip install -r requirements-dev.txt")
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch()
        except Exception as exc:
            if _in_ci():
                raise
            pytest.skip(
                "Playwright Chromium browser missing; run "
                "'python -m playwright install chromium' "
                f"({type(exc).__name__})")
        yield browser
        browser.close()


def _stub_dashboard_routes(page, base_url):
    payload = _forecast_payload()

    def route_handler(route):
        url = route.request.url
        if "query?type=forecast" in url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body=__import__("json").dumps(payload))
            return
        if "query?type=current" in url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"state":"ok","today_produced_kwh":1}')
            return
        if "query?type=dates" in url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"state":"ok","dates":[]}')
            return
        if "query?type=real_time" in url:
            route.fulfill(
                status=200,
                content_type="application/json",
                body='{"state":"ok","values":[]}')
            return
        if url.endswith("/name") or "/name?" in url:
            route.fulfill(status=200, body='"Test"')
            return
        route.continue_()

    page.route(f"{base_url}/**", route_handler)


def _cells_fit_wrapper(page):
    return page.evaluate("""() => {
        const wrap = document.getElementById('dash_forecast_week_wrap');
        if (!wrap) {
            return { ok: false, reason: 'no wrap' };
        }
        const wrect = wrap.getBoundingClientRect();
        const cells = document.querySelectorAll(
            '#dash_forecast_week_body td');
        for (const cell of cells) {
            const r = cell.getBoundingClientRect();
            if (r.right > wrect.right + 0.5) {
                return {
                    ok: false,
                    reason: 'overflow',
                    cellRight: r.right,
                    wrapRight: wrect.right,
                };
            }
        }
        return { ok: true };
    }""")


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("lang", ("en", "de", "fr"))
def test_forecast_week_cells_fit_on_real_dashboard(
        ui_server, playwright_browser, width, lang):
    page = playwright_browser.new_page(
        viewport={"width": width, "height": 900})
    _stub_dashboard_routes(page, ui_server)
    page.goto(ui_server + "/index.html", wait_until="networkidle")
    page.evaluate(LANG_SWITCH[lang] + "();")
    page.evaluate("showViewDashboard();")
    page.wait_for_selector("#dash_forecast_week_body tr", timeout=15000)
    result = _cells_fit_wrapper(page)
    assert result.get("ok"), result
    page.close()


def test_negative_control_old_css_clips_at_320(ui_server, playwright_browser):
    try:
        old_css = subprocess.check_output(
            ["git", "show", "f3f419f:site/css/custom.css"],
            cwd=ROOT,
            stderr=subprocess.DEVNULL,
        ).decode("utf-8")
    except (subprocess.CalledProcessError, FileNotFoundError):
        pytest.skip("git history for f3f419f unavailable")
    page = playwright_browser.new_page(
        viewport={"width": 320, "height": 900})
    _stub_dashboard_routes(page, ui_server)
    page.route(
        "**/css/custom.css",
        lambda route: route.fulfill(
            status=200, content_type="text/css", body=old_css))
    page.goto(ui_server + "/index.html", wait_until="networkidle")
    page.evaluate("switchLanguageToEnglish();")
    page.evaluate("showViewDashboard();")
    page.wait_for_selector("#dash_forecast_week_body tr", timeout=15000)
    result = _cells_fit_wrapper(page)
    page.close()
    assert not result.get("ok"), (
        "expected f3f419f CSS to clip at 320px (negative control)")
