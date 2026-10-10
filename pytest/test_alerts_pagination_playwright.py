'''Playwright tests for resolved-alert cursor paging in the UI.'''

import json
import socket
import threading
from datetime import datetime, timedelta, timezone
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

SITE = Path(__file__).resolve().parents[1] / "site"
PAGE_SIZE = 50


def _free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _make_resolved(n, start_id=1000):
    alerts = []
    base = datetime(2026, 3, 1, 12, 0, tzinfo=timezone.utc)
    for i in range(n):
        aid = start_id + i
        ended = (base - timedelta(hours=i)).isoformat()
        alerts.append({
            "id": aid,
            "rule_id": "grabber_stale",
            "severity": "critical",
            "title": "T",
            "message": "M",
            "started_at": ended,
            "ended_at": ended,
            "acknowledged_at": None,
            "status": "resolved",
            "detail": None,
        })
    return alerts


def _alerts_payload(resolved_all, cursor=None, limit=PAGE_SIZE):
    open_alerts = [{
        "id": 1,
        "rule_id": "device_unreachable",
        "severity": "critical",
        "title": "Open",
        "message": "M",
        "started_at": "2026-02-01T00:00:00+00:00",
        "ended_at": None,
        "acknowledged_at": None,
        "status": "open",
        "detail": None,
    }]
    start = 0
    if cursor:
        cur_id = int(cursor.split(",", 1)[1])
        for idx, row in enumerate(resolved_all):
            if row["id"] == cur_id:
                start = idx + 1
                break
    page = resolved_all[start:start + limit]
    has_more = start + limit < len(resolved_all)
    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = f"{last['ended_at']},{last['id']}"
    return {
        "state": "ok",
        "open_count": 1,
        "open_alerts": open_alerts,
        "recent_resolved": page,
        "resolved_has_more": has_more,
        "next_resolved_cursor": next_cursor,
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


def _stub_alerts_routes(page, base_url, resolved_all):
    state = {"resolved": list(resolved_all)}

    def route_handler(route):
        url = route.request.url
        if "query?type=alerts" in url:
            parsed = urlparse(url)
            qs = parse_qs(parsed.query)
            limit = int(qs.get("resolved_limit", ["50"])[0])
            cursor = qs.get("resolved_cursor", [None])[0]
            if "status=open" in url and "status=list" not in url:
                body = {
                    "state": "ok",
                    "open_count": 1,
                    "open_alerts": _alerts_payload(state["resolved"])["open_alerts"],
                }
            else:
                body = _alerts_payload(
                    state["resolved"], cursor=cursor, limit=limit)
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
    return state


def _list_alert_ids(page):
    return page.evaluate("""() => {
        return Array.from(
            document.querySelectorAll('#alerts_list li[data-alert-id]'))
            .map((li) => Number(li.dataset.alertId));
    }""")


@pytest.fixture
def alerts_page(ui_server, playwright_browser):
    resolved = _make_resolved(120)
    page = playwright_browser.new_page(
        viewport={"width": 1280, "height": 900})
    state = _stub_alerts_routes(page, ui_server, resolved)
    page.goto(ui_server + "/index.html", wait_until="networkidle")
    page.evaluate("showViewAlerts();")
    page.wait_for_selector("#alerts_list li", timeout=15000)
    yield page, state, resolved
    page.close()


def test_load_older_after_poll_advances_cursor(alerts_page):
    page, _state, _resolved = alerts_page
    page.click("#alerts_load_more_btn")
    page.wait_for_function(
        "() => document.querySelectorAll("
        "'#alerts_list li.text-muted').length >= 100")
    page.evaluate("refreshAlertsList({});")
    page.wait_for_timeout(800)
    page.click("#alerts_load_more_btn")
    page.wait_for_function(
        "() => document.querySelectorAll("
        "'#alerts_list li.text-muted').length > 100",
        timeout=15000)
    ids = _list_alert_ids(page)
    assert len(ids) == len(set(ids))
    assert len([i for i in ids if i != 1]) > 100


def test_live_alert_count_survives_language_switches(alerts_page):
    page, _state, _resolved = alerts_page
    for lang, expected in [(2, '1 offene Meldungen'), (3, '1 alertes ouvertes'),
                           (1, '1 open alerts')]:
        page.evaluate(f'switchLanguageByIndex({lang});')
        page.wait_for_function(
            'expected => document.getElementById("alerts_live_summary").textContent === expected',
            arg=expected)


def test_load_more_hidden_after_full_poll(alerts_page):
    page, state, resolved = alerts_page
    while page.is_visible("#alerts_load_more_btn"):
        page.click("#alerts_load_more_btn")
        page.wait_for_timeout(400)
    page.wait_for_function(
        "() => !document.getElementById('alerts_load_more_wrap')"
        " || document.getElementById('alerts_load_more_wrap').style.display === 'none'",
        timeout=15000)
    page.evaluate("refreshAlertsList({});")
    page.wait_for_timeout(500)
    visible = page.evaluate("""() => {
        const wrap = document.getElementById('alerts_load_more_wrap');
        if (!wrap) return false;
        return wrap.style.display !== 'none';
    }""")
    assert not visible


def test_burst_resolve_resets_list_when_page_does_not_overlap(alerts_page):
    page, state, _resolved = alerts_page
    page.click("#alerts_load_more_btn")
    page.wait_for_function(
        "() => document.querySelectorAll("
        "'#alerts_list li.text-muted').length >= 100",
        timeout=15000)
    state["resolved"] = _make_resolved(60, start_id=9000)
    page.evaluate("refreshAlertsList({});")
    page.wait_for_timeout(500)
    ids = _list_alert_ids(page)
    resolved_ids = [i for i in ids if i != 1]
    assert len(resolved_ids) == 50
    assert min(resolved_ids) >= 9000
    assert len(ids) == len(set(ids))


def test_obsolete_rule_shows_stored_title_not_raw_key(
        ui_server, playwright_browser):
    page = playwright_browser.new_page(viewport={"width": 375, "height": 800})
    resolved = []
    open_legacy = [{
        "id": 42,
        "rule_id": "counter_reset",
        "severity": "warning",
        "title": "Inverter counter reset detected",
        "message": "A cumulative energy counter dropped sharply.",
        "started_at": "2026-01-01T00:00:00+00:00",
        "ended_at": None,
        "acknowledged_at": None,
        "status": "open",
        "detail": None,
    }]

    def route_handler(route):
        url = route.request.url
        if "query?type=alerts" in url:
            body = {
                "state": "ok",
                "open_count": 1,
                "open_alerts": open_legacy,
                "recent_resolved": resolved,
                "resolved_has_more": False,
                "next_resolved_cursor": None,
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

    page.route(f"{ui_server}/**", route_handler)
    page.goto(ui_server + "/index.html", wait_until="networkidle")
    page.evaluate("showViewAlerts();")
    page.wait_for_selector("#alerts_list li strong", timeout=15000)
    title = page.locator("#alerts_list li strong").first.inner_text()
    assert title == "Inverter counter reset detected"
    assert title != "counter_reset"
    msg = page.locator("#alerts_list li p").first.inner_text()
    assert "counter dropped" in msg.lower()
    page.close()


def test_poll_after_paging_keeps_boundary_resolved_id(alerts_page):
    page, state, resolved = alerts_page
    boundary_id = resolved[49]["id"]
    page.click("#alerts_load_more_btn")
    page.wait_for_function(
        "() => document.querySelectorAll("
        "'#alerts_list li.text-muted').length >= 100")
    state["resolved"] = [{
        "id": 9999,
        "rule_id": "grabber_stale",
        "severity": "info",
        "title": "New",
        "message": "M",
        "started_at": "2026-03-01T12:00:00+00:00",
        "ended_at": "2026-03-01T12:00:00+00:00",
        "acknowledged_at": None,
        "status": "resolved",
        "detail": None,
    }] + state["resolved"]
    page.evaluate("refreshAlertsList({});")
    page.wait_for_timeout(400)
    ids = _list_alert_ids(page)
    assert boundary_id in ids
    assert 9999 in ids
    assert len(ids) == len(set(ids))
    assert len([i for i in ids if i != 1]) >= 101
