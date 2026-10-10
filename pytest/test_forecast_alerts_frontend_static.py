'''Frontend structure, localization coverage, and light behavioural checks.'''

import re
import subprocess
from pathlib import Path

import pytest


def test_forecast_alerts_js_exports_key_functions():
    text = Path("site/js/forecast_alerts.js").read_text(encoding="utf-8")
    for name in (
        "updateForecastDashboard",
        "refreshAlertsList",
        "clearForecastCardUi",
        "formatAlertTimestamp",
        "hideAlertsViewIfNeeded",
    ):
        assert ("function " + name) in text or name + "(" in text


def test_forecast_week_table_responsive_wrapper():
    html = Path("site/index.html").read_text(encoding="utf-8")
    assert 'id="dash_forecast_week_wrap" class="table-responsive"' in html
    css = Path("site/css/custom.css").read_text(encoding="utf-8")
    assert "forecast-week-table th" in css
    assert "white-space: normal" in css


def test_chart_summary_outside_fixed_chart_box():
    html = Path("site/index.html").read_text(encoding="utf-8")
    wrap_start = html.index('id="dash_forecast_chart_wrap"')
    wrap_end = html.index("</div>", wrap_start)
    wrap_chunk = html[wrap_start:wrap_end]
    assert "dash_forecast_chart_summary" not in wrap_chunk
    assert "dash_forecast_chart_summary" in html


def _hidden_span_ids(html):
    ids = set()
    for tag in re.findall(r"<[^>]+>", html):
        if "visually-hidden" not in tag:
            continue
        match = re.search(r'\bid="([^"]+)"', tag)
        if match:
            ids.add(match.group(1))
    return sorted(ids)


def _localization_ids(js_text):
    return {
        m.group(1)
        for m in re.finditer(r'\["([^"]+)",\s*"', js_text)
    }


def test_every_hidden_span_has_de_fr_localization():
    html = Path("site/index.html").read_text(encoding="utf-8")
    loc = Path("site/js/localization.js").read_text(encoding="utf-8")
    loc_ids = _localization_ids(loc)
    missing = []
    for span_id in _hidden_span_ids(html):
        if span_id not in loc_ids:
            missing.append(span_id)
    assert not missing, "missing localization rows: " + ", ".join(sorted(missing))


def test_localization_rows_have_three_languages():
    loc = Path("site/js/localization.js").read_text(encoding="utf-8")
    for line in loc.splitlines():
        if not line.strip().startswith('["'):
            continue
        if "forecast_" in line or "alerts_msg_" in line or "dash_forecast_chart" in line:
            parts = line.split('",')
            assert len(parts) >= 4, "expected EN/DE/FR for " + line[:60]


@pytest.mark.skipif(
    subprocess.run(
        ["which", "node"], capture_output=True).returncode != 0,
    reason="node not installed",
)
def test_forecast_stale_state_renders_values_js():
    script = r"""
const fs = require('fs');
const src = fs.readFileSync('site/js/forecast_alerts.js', 'utf8');
if (!src.includes('data.state !== "ok" && data.state !== "stale"')) {
  throw new Error('stale forecast must render like ok');
}
if (!src.includes('day_rollover')) {
  throw new Error('day_rollover must use unavailable notice');
}
if (!src.includes('forecastHasChartData')) {
  throw new Error('missing empty chart guard');
}
if (!src.includes('setForecastChartAccessibility')) {
  throw new Error('missing chart aria visibility guard');
}
console.log('ok');
"""
    proc = subprocess.run(
        ["node", "-e", script],
        cwd=Path(".").resolve(),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr or proc.stdout
