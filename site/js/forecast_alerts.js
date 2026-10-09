// Forecast and operational alerts UI.

let gForecastChart = null;
let gAlertsPollTimer = null;

function forecastStatusMessage(data) {
    if (!data || typeof data !== "object") {
        return getForecastUiString("unavailable");
    }
    switch (data.state) {
        case "ok":
            if (data.source === "open_meteo") {
                return getForecastUiString("source_open_meteo");
            }
            return getForecastUiString("source_history");
        case "disabled":
            return getForecastUiString("disabled");
        case "insufficient_history":
            return getForecastUiString("insufficient_history");
        case "unavailable":
        default:
            return getForecastUiString("unavailable");
    }
}

function getForecastUiString(id) {
    const el = document.getElementById("forecast_" + id);
    if (el) {
        return el.textContent;
    }
    return id;
}

function getAlertsUiString(id) {
    const el = document.getElementById("alerts_" + id);
    if (el) {
        return el.textContent;
    }
    return id;
}

function updateForecastDashboard() {
    if (!gDashboardVisible) {
        return;
    }
    fetchApiJson(gBaseUrl + "query?type=forecast").then(function (result) {
        const elStatus = document.getElementById("dash_forecast_status");
        const elToday = document.getElementById("dash_forecast_today_value");
        const elActual = document.getElementById("dash_forecast_actual_value");
        if (!elStatus) {
            return;
        }
        const data = result.data;
        if (!result.ok || !data) {
            elStatus.textContent = getForecastUiString("unavailable");
            setElementVisible("dash_forecast_chart_wrap", false);
            setElementVisible("dash_forecast_unavailable", true);
            return;
        }
        elStatus.textContent = forecastStatusMessage(data);
        if (data.state !== "ok") {
            setElementVisible("dash_forecast_chart_wrap", false);
            setElementVisible("dash_forecast_unavailable", true);
            if (elToday) {
                elToday.textContent = "—";
            }
            if (elActual) {
                elActual.textContent = "—";
            }
            return;
        }
        setElementVisible("dash_forecast_unavailable", false);
        setElementVisible("dash_forecast_chart_wrap", true);
        const forecastKwh = data.today_forecast_kwh;
        const actual = data.today_actual;
        if (elToday) {
            elToday.textContent = Number.isFinite(Number(forecastKwh))
                ? numFormat(forecastKwh, 1) : "—";
        }
        if (elActual) {
            const a = actual && Number.isFinite(Number(actual.production_kwh))
                ? actual.production_kwh : null;
            elActual.textContent = a !== null ? numFormat(a, 1) : "—";
        }
        renderForecastIntradayChart(data);
        renderForecastWeekTable(data.days || []);
    });
}

function renderForecastIntradayChart(data) {
    const canvas = document.getElementById("chart_forecast_intraday");
    if (!canvas || typeof Chart === "undefined") {
        return;
    }
    const labels = [];
    for (let h = 0; h < 24; h++) {
        labels.push(pad2(h) + ":00");
    }
    const forecast = (data.hourly_today_cumulative || []).slice(0, 24);
    while (forecast.length < 24) {
        forecast.push(null);
    }
    const datasets = [{
        label: getForecastUiString("cumulative_forecast"),
        data: forecast,
        borderColor: "#f39c12",
        backgroundColor: "rgba(243,156,18,0.1)",
        fill: true,
        tension: 0.2,
    }];
    if (gForecastChart) {
        gForecastChart.data.labels = labels;
        gForecastChart.data.datasets = datasets;
        gForecastChart.update();
        return;
    }
    gForecastChart = new Chart(canvas.getContext("2d"), {
        type: "line",
        data: { labels, datasets },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: true } },
            scales: {
                y: {
                    beginAtZero: true,
                    title: { display: true, text: "kWh" },
                },
            },
        },
    });
}

function renderForecastWeekTable(days) {
    const tbody = document.getElementById("dash_forecast_week_body");
    if (!tbody) {
        return;
    }
    tbody.innerHTML = "";
    const slice = days.slice(0, 7);
    for (const row of slice) {
        const tr = document.createElement("tr");
        tr.innerHTML = "<td>" + row.date + "</td><td class=\"text-end\">"
            + numFormat(row.production_kwh, 1) + "</td><td class=\"text-end\">"
            + numFormat(row.consumption_kwh, 1) + "</td>";
        tbody.appendChild(tr);
    }
}

function updateAlertsBadge() {
    fetchApiJson(gBaseUrl + "query?type=alerts&status=open&limit=20").then(function (result) {
        const badge = document.getElementById("sidebar_alerts_badge");
        if (!badge) {
            return;
        }
        const count = result.data && Number.isFinite(Number(result.data.open_count))
            ? Number(result.data.open_count) : 0;
        if (count > 0) {
            badge.textContent = String(count);
            badge.style.display = "inline";
        } else {
            badge.style.display = "none";
        }
    });
}

function showViewAlerts() {
    bumpViewGeneration();
    setElementVisible("view_dashboard", false);
    setElementVisible("view_statistics", false);
    setElementVisible("view_history", false);
    setElementVisible("view_csv", false);
    setElementVisible("view_alerts", true);
    setInfoGraphicEnabled(false);
    gDashboardVisible = false;
    setSidebarActive("alerts");
    refreshAlertsList();
    if (!gAlertsPollTimer) {
        gAlertsPollTimer = setInterval(refreshAlertsList, 15000);
    }
}

function hideAlertsViewIfNeeded() {
    setElementVisible("view_alerts", false);
}

function refreshAlertsList() {
    fetchApiJson(gBaseUrl + "query?type=alerts&limit=80").then(function (result) {
        const list = document.getElementById("alerts_list");
        const empty = document.getElementById("alerts_none_banner");
        if (!list) {
            return;
        }
        list.innerHTML = "";
        const alerts = (result.data && result.data.alerts) || [];
        const open = alerts.filter(function (a) { return a.status === "open"; });
        if (empty) {
            setElementVisible("alerts_none_banner", open.length === 0);
        }
        for (const alert of alerts) {
            const li = document.createElement("li");
            li.className = "list-group-item";
            const sev = alert.severity || "warning";
            const ack = alert.acknowledged_at ? " (" + getAlertsUiString("acknowledged") + ")" : "";
            li.innerHTML = "<div class=\"d-flex w-100 justify-content-between\">"
                + "<strong class=\"text-" + severityBootstrapClass(sev) + "\">"
                + escapeHtml(alert.title) + "</strong>"
                + "<small>" + escapeHtml(alert.started_at || "") + "</small></div>"
                + "<p class=\"mb-1\">" + escapeHtml(alert.message) + ack + "</p>"
                + "<small class=\"text-muted\">" + escapeHtml(alert.rule_id)
                + " · " + escapeHtml(alert.status) + "</small>";
            if (alert.status === "open" && !alert.acknowledged_at) {
                const btn = document.createElement("button");
                btn.type = "button";
                btn.className = "btn btn-sm btn-outline-secondary mt-2";
                btn.textContent = getAlertsUiString("acknowledge");
                btn.onclick = function () { acknowledgeAlert(alert.id); };
                li.appendChild(btn);
            }
            list.appendChild(li);
        }
        updateAlertsBadge();
    });
}

function severityBootstrapClass(sev) {
    if (sev === "critical") {
        return "danger";
    }
    if (sev === "info") {
        return "secondary";
    }
    return "warning";
}

function escapeHtml(text) {
    const div = document.createElement("div");
    div.textContent = text == null ? "" : String(text);
    return div.innerHTML;
}

function acknowledgeAlert(id) {
    fetch(gBaseUrl + "alerts/acknowledge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: id }),
    }).then(function () {
        refreshAlertsList();
    });
}
