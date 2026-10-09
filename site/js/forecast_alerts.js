// Forecast and operational alerts UI.

let gForecastChart = null;
let gAlertsPollTimer = null;
let gAlertsViewVisible = false;
let gLastAlertsRenderKey = "";
let gLastAlertsLiveSummary = "";
let gLastForecastChartSummary = "";
let gResolvedAlertsOffset = 0;
let gResolvedAlertsHasMore = false;
let gResolvedAlertsCache = [];

const ALERT_RULE_STRINGS = {
    device_unreachable: ["Device unreachable", "Gerät nicht erreichbar", "Appareil inaccessible"],
    grabber_stale: ["Data recording stalled", "Datenerfassung gestoppt", "Enregistrement interrompu"],
    zero_production_daylight: ["No production during daylight", "Keine Erzeugung bei Tageslicht", "Pas de production de jour"],
    production_below_forecast: ["Production below forecast", "Erzeugung unter Prognose", "Production sous la prévision"],
    production_below_baseline: ["Production below baseline", "Erzeugung unter dem Durchschnitt", "Production sous la moyenne"],
    production_spike: ["Unusual production spike", "Ungewöhnliche Erzeugungsspitze", "Pic de production inhabituel"],
    consumption_spike: ["Unusual consumption spike", "Ungewöhnliche Verbrauchsspitze", "Pic de consommation inhabituel"],
    counter_reset: ["Counter reset detected", "Zähler-Reset erkannt", "Réinitialisation du compteur"],
    negative_delta: ["Implausible counter decrease", "Unplausibler Zählerabfall", "Baisse de compteur incohérente"],
    battery_low_soc: ["Battery charge low", "Batterieladung niedrig", "Charge batterie faible"],
    battery_stuck: ["Battery level unchanged", "Batteriestand unverändert", "Niveau batterie inchangé"],
};

const ALERT_STATUS_STRINGS = {
    open: ["Open", "Offen", "Ouverte"],
    resolved: ["Resolved", "Behoben", "Résolue"],
};

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
        case "pending":
            return getForecastUiString("pending");
        case "stale":
            return getForecastUiString("stale");
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
    if (typeof getTranslationString === "function") {
        const tr = getTranslationString("alerts_" + id);
        if (tr) {
            return tr;
        }
        const side = getTranslationString("sidebar_alerts_" + id);
        if (side) {
            return side;
        }
    }
    return id;
}

function clearForecastCardUi() {
    const elToday = document.getElementById("dash_forecast_today_value");
    const elActual = document.getElementById("dash_forecast_actual_value");
    if (elToday) {
        elToday.textContent = "—";
    }
    if (elActual) {
        elActual.textContent = "—";
    }
    const tbody = document.getElementById("dash_forecast_week_body");
    if (tbody) {
        tbody.innerHTML = "";
    }
    setElementVisible("dash_forecast_week_wrap", false);
    setElementVisible("dash_forecast_chart_wrap", false);
    if (gForecastChart) {
        gForecastChart.destroy();
        gForecastChart = null;
    }
    setForecastChartSummaryText("");
}

function setForecastChartSummaryText(text) {
    const summary = document.getElementById("dash_forecast_chart_summary");
    if (!summary) {
        return;
    }
    if (text === gLastForecastChartSummary) {
        return;
    }
    gLastForecastChartSummary = text;
    summary.textContent = text;
}

function instanceTodayYmd() {
    if (gReferenceTodayYmd) {
        return gReferenceTodayYmd;
    }
    const parts = getInstanceWallClockParts();
    if (!parts) {
        return null;
    }
    const now = new Date();
    return now.getUTCFullYear() + "-"
        + pad2(now.getUTCMonth() + 1) + "-"
        + pad2(now.getUTCDate());
}

function forecastHasChartData(data) {
    const cumulative = data.hourly_today_cumulative || [];
    return cumulative.some(function (v) {
        return v !== null && Number(v) > 0;
    });
}

function setForecastCardNonOk(data) {
    const elStatus = document.getElementById("dash_forecast_status");
    if (elStatus) {
        elStatus.textContent = forecastStatusMessage(data);
    }
    clearForecastCardUi();
    setElementVisible("dash_forecast_unavailable", true);
}

function updateForecastDashboard() {
    if (!gDashboardVisible) {
        return;
    }
    fetchApiJson(gBaseUrl + "query?type=forecast").then(function (result) {
        const elStatus = document.getElementById("dash_forecast_status");
        if (!elStatus) {
            return;
        }
        const data = result.data;
        if (!result.ok || !data) {
            setForecastCardNonOk({ state: "unavailable" });
            return;
        }
        const todayYmd = instanceTodayYmd();
        if (data.state === "ok" && todayYmd && data.today && data.today !== todayYmd) {
            setForecastCardNonOk({ state: "stale" });
            return;
        }
        if (data.state !== "ok" && data.state !== "stale") {
            setForecastCardNonOk(data);
            return;
        }
        setElementVisible("dash_forecast_unavailable", false);
        elStatus.textContent = forecastStatusMessage(data);
        const forecastKwh = data.today_forecast_kwh;
        const actual = data.today_actual;
        const elToday = document.getElementById("dash_forecast_today_value");
        const elActual = document.getElementById("dash_forecast_actual_value");
        if (elToday) {
            elToday.textContent = Number.isFinite(Number(forecastKwh))
                ? numFormat1(forecastKwh) : "—";
        }
        if (elActual) {
            const a = actual && Number.isFinite(Number(actual.production_kwh))
                ? actual.production_kwh : null;
            elActual.textContent = a !== null ? numFormat1(a) : "—";
        }
        const hasChart = forecastHasChartData(data);
        setElementVisible("dash_forecast_chart_wrap", hasChart);
        setElementVisible("dash_forecast_week_wrap", true);
        if (hasChart) {
            renderForecastIntradayChart(data);
        } else {
            setForecastChartSummaryText("");
            if (gForecastChart) {
                gForecastChart.destroy();
                gForecastChart = null;
            }
        }
        renderForecastWeekTable(data.days || [], data.today);
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
        borderColor: "#b45309",
        backgroundColor: "rgba(180,83,9,0.12)",
        fill: true,
        tension: 0.2,
    }];
    const peak = forecast.reduce(function (m, v) {
        return (v !== null && v > m) ? v : m;
    }, 0);
    setForecastChartSummaryText(
        getForecastUiString("chart_summary").replace("%s", numFormat1(peak)));
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

function formatForecastWeekDate(ymd) {
    if (!ymd || !/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(ymd)) {
        return ymd || "";
    }
    const d = new Date(ymd + "T12:00:00");
    return d.toLocaleDateString(getLocale(), {
        weekday: "short",
        day: "numeric",
        month: "short",
    });
}

function renderForecastWeekTable(days, todayYmd) {
    const tbody = document.getElementById("dash_forecast_week_body");
    if (!tbody) {
        return;
    }
    tbody.innerHTML = "";
    const slice = days.slice(0, 7);
    for (const row of slice) {
        const tr = document.createElement("tr");
        const tdDate = document.createElement("td");
        tdDate.textContent = formatForecastWeekDate(row.date);
        const tdProd = document.createElement("td");
        tdProd.className = "text-end";
        tdProd.textContent = numFormat1(row.production_kwh);
        const tdCons = document.createElement("td");
        tdCons.className = "text-end";
        tdCons.textContent = numFormat1(row.consumption_kwh);
        tr.appendChild(tdDate);
        tr.appendChild(tdProd);
        tr.appendChild(tdCons);
        tbody.appendChild(tr);
    }
}

function updateAlertsBadge() {
    fetchApiJson(gBaseUrl + "query?type=alerts&status=open").then(function (result) {
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
        const summary = document.getElementById("alerts_live_summary");
        if (summary) {
            const text = getAlertsUiString("open_count_summary")
                .replace("%s", String(count));
            if (text !== gLastAlertsLiveSummary) {
                gLastAlertsLiveSummary = text;
                summary.textContent = text;
            }
        }
        const badgeLabel = document.getElementById("sidebar_alerts_badge_label");
        if (badgeLabel) {
            const labelText = count > 0
                ? (typeof getTranslationString === "function"
                    ? getTranslationString("sidebar_alerts_badge_with_count")
                    : getAlertsUiString("sidebar_badge_with_count"))
                    .replace("%s", String(count))
                : "";
            if (badgeLabel.textContent !== labelText) {
                badgeLabel.textContent = labelText;
            }
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
    gAlertsViewVisible = true;
    setSidebarActive("alerts");
    initAlertsLoadMore();
    refreshAlertsList(true);
    if (!gAlertsPollTimer) {
        gAlertsPollTimer = setInterval(function () {
            if (gAlertsViewVisible) {
                initAlertsLoadMore();
    refreshAlertsList(true);
            }
        }, 15000);
    }
}

function hideAlertsViewIfNeeded() {
    gAlertsViewVisible = false;
    setElementVisible("view_alerts", false);
}

function localizedAlertRuleTitle(ruleId) {
    const row = ALERT_RULE_STRINGS[ruleId];
    if (!row) {
        return ruleId;
    }
    return row[gCurLang - 1] || row[0];
}

function localizedAlertStatus(status) {
    const row = ALERT_STATUS_STRINGS[status];
    if (!row) {
        return status;
    }
    return row[gCurLang - 1] || row[0];
}

function formatAlertTimestamp(iso) {
    if (!iso) {
        return "";
    }
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) {
        return "";
    }
    const opts = {
        dateStyle: "short",
        timeStyle: "short",
    };
    if (gInstanceTimeZone && gInstanceTimeZoneValid) {
        opts.timeZone = gInstanceTimeZone;
    }
    let formatted = d.toLocaleString(getTimeLocaleTag(), opts);
    const tzLabel = formatInstanceTimeZoneShortLabel(getTimeLocaleTag());
    if (tzLabel) {
        formatted += " " + tzLabel;
    }
    return formatted;
}

function alertsRenderKey(alerts) {
    return alerts.map(function (a) {
        return [
            a.id, a.status, a.acknowledged_at || "",
            a.ended_at || "", a.started_at || "",
        ].join(":");
    }).join("|");
}

function renderAlertsListDom(openAlerts, resolvedAlerts) {
    const list = document.getElementById("alerts_list");
    const empty = document.getElementById("alerts_none_banner");
    if (!list) {
        return;
    }
    const combined = openAlerts.concat(resolvedAlerts);
    const key = alertsRenderKey(combined);
    if (key === gLastAlertsRenderKey) {
        return;
    }
    const focusedId = document.activeElement
        && document.activeElement.dataset
        ? document.activeElement.dataset.alertAckId : null;

    list.innerHTML = "";
    if (empty) {
        setElementVisible("alerts_none_banner", openAlerts.length === 0);
    }
    function appendAlert(alert) {
        const li = document.createElement("li");
        li.className = "list-group-item";
        if (alert.status === "resolved") {
            li.classList.add("text-muted");
        }
        const sev = alert.severity || "warning";
        const header = document.createElement("div");
        header.className = "alert-item-header";
        const title = document.createElement("strong");
        title.className = severityTitleClass(sev, alert.status);
        title.textContent = localizedAlertRuleTitle(alert.rule_id);
        const timeEl = document.createElement("small");
        timeEl.className = "alert-item-time text-muted";
        timeEl.textContent = formatAlertTimestamp(alert.started_at);
        header.appendChild(title);
        header.appendChild(timeEl);
        li.appendChild(header);
        const msg = document.createElement("p");
        msg.className = "mb-1";
        msg.textContent = formatAlertMessage(alert);
        li.appendChild(msg);
        const meta = document.createElement("small");
        meta.className = "text-muted";
        meta.textContent = localizedAlertStatus(alert.status);
        if (alert.acknowledged_at) {
            meta.textContent += " · " + getAlertsUiString("acknowledged");
        }
        li.appendChild(meta);
        if (alert.status === "open" && !alert.acknowledged_at) {
            const btn = document.createElement("button");
            btn.type = "button";
            btn.className = "btn btn-sm btn-outline-secondary mt-2";
            btn.textContent = getAlertsUiString("acknowledge");
            btn.dataset.alertAckId = String(alert.id);
            btn.onclick = function () { acknowledgeAlert(alert.id); };
            li.appendChild(btn);
        }
        list.appendChild(li);
    }
    for (const alert of openAlerts) {
        appendAlert(alert);
    }
    for (const alert of resolvedAlerts) {
        appendAlert(alert);
    }
    gLastAlertsRenderKey = key;
    if (focusedId) {
        const btn = list.querySelector('[data-alert-ack-id="' + focusedId + '"]');
        if (btn) {
            btn.focus();
        }
    }
}

function formatAlertMessage(alert) {
    const d = alert.detail || {};
    const rule = alert.rule_id;
    const msgKey = "msg_" + rule;
    const localized = getAlertsUiString(msgKey);
    if (localized !== msgKey) {
        if (rule === "battery_low_soc") {
            return localized.replace(
                "%s", String(d.soc_percent != null ? d.soc_percent : "?"));
        }
        return localized;
    }
    switch (rule) {
        case "battery_low_soc":
            return getAlertsUiString("msg_battery_low")
                .replace("%s", String(d.soc_percent != null ? d.soc_percent : "?"));
        case "device_unreachable":
            return getAlertsUiString("msg_device_unreachable");
        case "grabber_stale":
            return getAlertsUiString("msg_grabber_stale");
        default:
            return getAlertsUiString("msg_generic");
    }
}

function severityTitleClass(sev, status) {
    if (status === "resolved") {
        return "";
    }
    if (sev === "critical") {
        return "text-danger";
    }
    if (sev === "info") {
        return "text-secondary";
    }
    return "alert-title-warning";
}

function refreshAlertsList(resetResolved) {
    if (resetResolved) {
        gResolvedAlertsOffset = 0;
        gResolvedAlertsCache = [];
    }
    const url = gBaseUrl + "query?type=alerts&status=list"
        + "&resolved_offset=" + String(gResolvedAlertsOffset);
    fetchApiJson(url).then(function (result) {
        if (!result.ok || !result.data) {
            return;
        }
        const openAlerts = result.data.open_alerts || [];
        let resolvedAlerts = result.data.recent_resolved || [];
        gResolvedAlertsHasMore = Boolean(result.data.resolved_has_more);
        if (gResolvedAlertsOffset === 0) {
            gResolvedAlertsCache = resolvedAlerts.slice();
        } else {
            gResolvedAlertsCache = gResolvedAlertsCache.concat(resolvedAlerts);
        }
        resolvedAlerts = gResolvedAlertsCache;
        renderAlertsListDom(openAlerts, resolvedAlerts);
        const moreWrap = document.getElementById("alerts_load_more_wrap");
        const moreBtn = document.getElementById("alerts_load_more_btn");
        if (moreWrap) {
            setElementVisible("alerts_load_more_wrap", gResolvedAlertsHasMore);
        }
        if (moreBtn && !moreBtn.dataset.bound) {
            moreBtn.dataset.bound = "1";
            moreBtn.onclick = function () {
                gResolvedAlertsOffset += 50;
                refreshAlertsList(false);
            };
        }
        updateAlertsBadge();
    });
}

function initAlertsLoadMore() {
    const moreBtn = document.getElementById("alerts_load_more_btn");
    if (moreBtn && typeof getTranslationString === "function") {
        const label = getTranslationString("alerts_load_more_btn");
        if (label) {
            moreBtn.textContent = label;
        }
    }
}

function acknowledgeAlert(id) {
    const errEl = document.getElementById("alerts_ack_error");
    if (errEl) {
        errEl.style.display = "none";
    }
    fetch(gBaseUrl + "alerts/acknowledge", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ id: id }),
    }).then(function (response) {
        if (!response.ok) {
            throw new Error("http_" + response.status);
        }
        return response.json();
    }).then(function () {
        gLastAlertsRenderKey = "";
        initAlertsLoadMore();
    refreshAlertsList(true);
    }).catch(function () {
        if (errEl) {
            errEl.textContent = getAlertsUiString("ack_failed");
            errEl.style.display = "block";
        }
    });
}
