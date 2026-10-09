'''Alert message strings use localized copy for known rules.'''

import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SITE = Path(__file__).resolve().parents[1] / "site"

KNOWN_RULES = [
    ("device_unreachable", "msg_device_unreachable", {}),
    ("grabber_stale", "msg_grabber_stale", {}),
    ("battery_low_soc", "msg_battery_low", {"detail": {"soc_percent": 7}}),
    ("zero_production_daylight", "msg_zero_production_daylight", {}),
    ("production_below_forecast", "msg_production_below_forecast", {}),
    ("production_below_baseline", "msg_production_below_baseline", {}),
    ("production_spike", "msg_production_spike", {}),
    ("consumption_spike", "msg_consumption_spike", {}),
    ("battery_stuck", "msg_battery_stuck", {}),
]

TITLE_RULES = [
    ("device_unreachable", "Device unreachable"),
    ("counter_reset", None),
]


@pytest.fixture(scope="module")
def ui_server():
    import socket
    import threading

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
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
        pytest.skip("playwright not installed")
    with sync_playwright() as p:
        browser = p.chromium.launch()
        yield browser
        browser.close()


def _stub_alerts(page, base_url, open_alerts):
    def route_handler(route):
        url = route.request.url
        if "query?type=alerts" in url:
            body = {
                "state": "ok",
                "open_count": len(open_alerts),
                "open_alerts": open_alerts,
                "recent_resolved": [],
                "resolved_has_more": False,
            }
            route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps(body))
            return
        if url.endswith("/name") or "/name?" in url:
            route.fulfill(status=200, body='"Test"')
            return
        route.continue_()

    page.route(f"{base_url}/**", route_handler)


@pytest.mark.parametrize("lang", [1, 2, 3])
@pytest.mark.parametrize(
    "rule_id,msg_key,extra",
    KNOWN_RULES,
)
def test_known_rule_renders_localized_message(
        ui_server, playwright_browser, lang, rule_id, msg_key, extra):
    page = playwright_browser.new_page(viewport={"width": 400, "height": 700})
    alert = {
        "id": 99,
        "rule_id": rule_id,
        "severity": "warning",
        "title": "Stored English title",
        "message": "Stored English message should not show",
        "started_at": "2026-01-01T00:00:00+00:00",
        "ended_at": None,
        "acknowledged_at": None,
        "status": "open",
        "detail": extra.get("detail"),
    }
    _stub_alerts(page, ui_server, [alert])
    page.goto(ui_server + "/index.html", wait_until="networkidle")
    page.evaluate(f"switchLanguageByIndex({lang});")
    page.evaluate("showViewAlerts();")
    page.wait_for_selector("#alerts_list li p", timeout=15000)
    expected = page.evaluate(
        f"() => getTranslationString('alerts_{msg_key}')")
    rendered = page.locator("#alerts_list li p").first.inner_text()
    if rule_id == "battery_low_soc":
        expected = expected.replace("%s", "7")
    assert rendered == expected
    if lang != 1:
        assert "Stored English message" not in rendered
    page.close()


@pytest.mark.parametrize("lang", [1, 2, 3])
@pytest.mark.parametrize("rule_id,en_title", TITLE_RULES)
def test_known_rule_renders_localized_title(
        ui_server, playwright_browser, lang, rule_id, en_title):
    page = playwright_browser.new_page(viewport={"width": 400, "height": 700})
    alert = {
        "id": 100,
        "rule_id": rule_id,
        "severity": "critical",
        "title": "Stored English title",
        "message": "x",
        "started_at": "2026-01-01T00:00:00+00:00",
        "status": "open",
    }
    _stub_alerts(page, ui_server, [alert])
    page.goto(ui_server + "/index.html", wait_until="networkidle")
    page.evaluate(f"switchLanguageByIndex({lang});")
    page.evaluate("showViewAlerts();")
    page.wait_for_selector("#alerts_list li strong", timeout=15000)
    if en_title:
        expected = page.evaluate(
            f"() => ALERT_RULE_STRINGS['{rule_id}'][{lang} - 1]")
    elif lang == 1:
        expected = "Stored English title"
    else:
        expected = page.evaluate(
            "() => getTranslationString('alerts_unknown_rule_title')")
    rendered = page.locator("#alerts_list li strong").first.inner_text()
    assert rendered == expected
    if lang != 1 and not en_title:
        assert "Stored English title" not in rendered
    page.close()


def test_battery_low_soc_missing_soc_uses_generic(ui_server, playwright_browser):
    page = playwright_browser.new_page(viewport={"width": 400, "height": 700})
    alert = {
        "id": 101,
        "rule_id": "battery_low_soc",
        "severity": "warning",
        "title": "Battery low",
        "message": "legacy",
        "started_at": "2026-01-01T00:00:00+00:00",
        "status": "open",
        "detail": {},
    }
    _stub_alerts(page, ui_server, [alert])
    page.goto(ui_server + "/index.html", wait_until="networkidle")
    page.evaluate("showViewAlerts();")
    page.wait_for_selector("#alerts_list li p", timeout=15000)
    expected = page.evaluate(
        "() => getTranslationString('alerts_msg_generic')")
    assert page.locator("#alerts_list li p").first.inner_text() == expected
    page.close()
