'''Lightweight checks for forecast/alerts frontend assets.'''

from pathlib import Path


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


def test_forecast_tables_scoped_in_css():
    css = Path("site/css/custom.css").read_text(encoding="utf-8")
    assert "dash-energy-table" in css
    assert "forecast-summary-table" in css


def test_index_forecast_table_classes():
    html = Path("site/index.html").read_text(encoding="utf-8")
    assert "forecast-summary-table" in html
    assert "dash-energy-table" in html
