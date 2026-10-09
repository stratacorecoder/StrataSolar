// Forecast and operational alerts UI.

let gForecastChart = null;
let gAlertsPollTimer = null;
let gAlertsViewVisible = false;
let gLastAlertsRenderKey = "";
let gLastAlertsLiveSummary = "";
let gLastForecastChartSummary = "";
const RESOLVED_PAGE_SIZE = 50;
let gResolvedAlertsHasMore = false;
let gResolvedAlertsCache = [];
let gResolvedNextCursor = null;
let gLastOpenAlertsCache = [];
let gForecastRolloverRetryDelayMs = 5000;
let gForecastRolloverRetryTimer = null;
let gResolvedEndReached = false;

const ALERT_RULE_STRINGS = {
    device_unreachable: ["Device unreachable", "Gerät nicht erreichbar", "Appareil inaccessible"],
    grabber_stale: ["Data recording stalled", "Datenerfassung gestoppt", "Enregistrement interrompu"],
    zero_production_daylight: ["No production during daylight", "Keine Erzeugung bei Tageslicht", "Pas de production de jour"],
    production_below_forecast: ["Production below forecast", "Erzeugung unter Prognose", "Production sous la prévision"],
    production_below_baseline: ["Production below baseline", "Erzeugung unter dem Durchschnitt", "Production sous la moyenne"],
    production_spike: ["Unusual production spike", "Ungewöhnliche Erzeugungsspitze", "Pic de production inhabituel"],
    consumption_spike: ["Unusual consumption spike", "Ungewöhnliche Verbrauchsspitze", "Pic de consommation inhabituel"],
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
    setForecastChartAccessibility(false);
    if (gForecastChart) {
        gForecastChart.destroy();
        gForecastChart = null;
    }
    setForecastChartSummaryText("");
}

function setForecastChartAccessibility(visible) {
    const ariaEl = document.getElementById("dash_forecast_chart_aria_label");
    const canvas = document.getElementById("chart_forecast_intraday");
    if (ariaEl) {
        if (visible) {
            ariaEl.removeAttribute("hidden");
            ariaEl.setAttribute("aria-hidden", "false");
        } else {
            ariaEl.setAttribute("hidden", "");
            ariaEl.setAttribute("aria-hidden", "true");
        }
    }
    if (canvas) {
        if (visible) {
            canvas.setAttribute("aria-labelledby", "dash_forecast_chart_aria_label");
        } else {
            canvas.removeAttribute("aria-labelledby");
        }
    }
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
    if (gInstanceUtcOffsetMinutes != null
            && Number.isFinite(gInstanceUtcOffsetMinutes)) {
        const localMs = Date.now() + gInstanceUtcOffsetMinutes * 60000;
        const d = new Date(localMs);
        return d.getUTCFullYear() + "-"
            + pad2(d.getUTCMonth() + 1) + "-"
            + pad2(d.getUTCDate());
    }
    if (gInstanceTimeZone && gInstanceTimeZoneValid) {
        try {
            const parts = new Intl.DateTimeFormat("en-CA", {
                timeZone: gInstanceTimeZone,
                year: "numeric",
                month: "2-digit",
                day: "2-digit",
            }).formatToParts(new Date());
            const y = parts.find(function (p) { return p.type === "year"; });
            const m = parts.find(function (p) { return p.type === "month"; });
            const day = parts.find(function (p) { return p.type === "day"; });
            if (y && m && day) {
                return y.value + "-" + m.value + "-" + day.value;
            }
        } catch (formatError) {
            // Fall through.
        }
    }
    return null;
}

function forecastHasChartData(data) {
    const cumulative = data.hourly_today_cumulative || [];
    return cumulative.some(function (v) {
        return v !== null && Number(v) > 0;
    });
}

function resetForecastRolloverRetryState() {
    gForecastRolloverRetryDelayMs = 5000;
    if (gForecastRolloverRetryTimer) {
        clearTimeout(gForecastRolloverRetryTimer);
        gForecastRolloverRetryTimer = null;
    }
}

function scheduleForecastRolloverRetry() {
    if (gForecastRolloverRetryTimer) {
        return;
    }
    const delay = gForecastRolloverRetryDelayMs;
    gForecastRolloverRetryTimer = setTimeout(function () {
        gForecastRolloverRetryTimer = null;
        gForecastRolloverRetryDelayMs = Math.min(
            60000, Math.max(5000, gForecastRolloverRetryDelayMs * 2));
        updateForecastDashboard();
    }, delay);
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
            scheduleForecastRolloverRetry();
            return;
        }
        if (data.state === "stale" && data.reason === "day_rollover") {
            setForecastCardNonOk(data);
            scheduleForecastRolloverRetry();
            return;
        }
        if (data.state !== "ok" && data.state !== "stale") {
            setForecastCardNonOk(data);
            return;
        }
        const todayNow = instanceTodayYmd();
        if (todayNow && data.today && data.today !== todayNow) {
            setForecastCardNonOk({ state: "stale", reason: "day_rollover" });
            scheduleForecastRolloverRetry();
            return;
        }
        const weekDays = data.days || [];
        if (weekDays.length === 0) {
            setForecastCardNonOk({
                state: data.state === "stale" ? "stale" : "unavailable",
            });
            return;
        }
        resetForecastRolloverRetryState();
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
        setForecastChartAccessibility(hasChart);
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
        renderForecastWeekTable(weekDays, data.today);
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

function forecastWeekMetricLabel(kind) {
    const fullId = kind === "prod"
        ? "dash_forecast_week_head_prod"
        : "dash_forecast_week_head_cons";
    if (typeof getTranslationString === "function") {
        const fullLabel = getTranslationString(fullId);
        if (fullLabel) {
            return fullLabel;
        }
    }
    const el = document.getElementById(fullId);
    return el ? el.textContent : (kind === "prod" ? "Production" : "Consumption");
}

function renderForecastWeekTable(days, todayYmd) {
    const tbody = document.getElementById("dash_forecast_week_body");
    if (!tbody) {
        return;
    }
    tbody.innerHTML = "";
    const slice = days.slice(0, 7);
    const prodLabel = forecastWeekMetricLabel("prod");
    const consLabel = forecastWeekMetricLabel("cons");
    for (const row of slice) {
        const tr = document.createElement("tr");
        tr.setAttribute("role", "row");
        const tdDate = document.createElement("td");
        tdDate.setAttribute("role", "cell");
        tdDate.className = "forecast-week-date";
        tdDate.textContent = formatForecastWeekDate(row.date);
        tr.appendChild(tdDate);
        tr.appendChild(
            createForecastWeekMetricCell(prodLabel, row.production_kwh));
        tr.appendChild(
            createForecastWeekMetricCell(consLabel, row.consumption_kwh));
        tbody.appendChild(tr);
    }
}

function createForecastWeekMetricCell(label, kwh) {
    const td = document.createElement("td");
    td.setAttribute("role", "cell");
    td.className = "text-end forecast-week-metric";
    td.dataset.label = label;
    const val = document.createElement("span");
    val.className = "forecast-week-value";
    val.textContent = numFormat1(kwh);
    td.appendChild(val);
    return td;
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
    refreshAlertsList({ reset: true });
    if (!gAlertsPollTimer) {
        gAlertsPollTimer = setInterval(function () {
            if (gAlertsViewVisible) {
                refreshAlertsList({});
            }
        }, 15000);
    }
}

function hideAlertsViewIfNeeded() {
    gAlertsViewVisible = false;
    setElementVisible("view_alerts", false);
}

function localizedAlertRuleTitle(alert) {
    const ruleId = alert.rule_id || "";
    const row = Object.prototype.hasOwnProperty.call(
        ALERT_RULE_STRINGS, ruleId)
        ? ALERT_RULE_STRINGS[ruleId] : null;
    if (row) {
        return row[gCurLang - 1] || row[0];
    }
    if (gCurLang !== gLangEn) {
        const genericTitle = getAlertsUiString("unknown_rule_title");
        if (genericTitle && genericTitle !== "unknown_rule_title") {
            return genericTitle;
        }
    }
    if (alert.title) {
        return alert.title;
    }
    const genericTitle = getAlertsUiString("unknown_rule_title");
    if (genericTitle && genericTitle !== "unknown_rule_title") {
        return genericTitle;
    }
    return ruleId;
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

function renderAlertsListDom(openAlerts, resolvedAlerts, fetchError) {
    const list = document.getElementById("alerts_list");
    const empty = document.getElementById("alerts_none_banner");
    if (!list) {
        return;
    }
    const combined = openAlerts.concat(resolvedAlerts);
    const key = alertsRenderKey(combined) + "|" + (fetchError ? "e" : "o");
    if (key === gLastAlertsRenderKey) {
        return;
    }
    const focusedId = document.activeElement
        && document.activeElement.dataset
        ? document.activeElement.dataset.alertAckId : null;

    list.innerHTML = "";
    if (empty) {
        setElementVisible(
            "alerts_none_banner", openAlerts.length === 0 && !fetchError);
    }
    function appendAlert(alert) {
        const li = document.createElement("li");
        li.className = "list-group-item";
        li.dataset.alertId = String(alert.id);
        if (alert.status === "resolved") {
            li.classList.add("text-muted");
        }
        const sev = alert.severity || "warning";
        const header = document.createElement("div");
        header.className = "alert-item-header";
        const title = document.createElement("strong");
        title.className = severityTitleClass(sev, alert.status);
        title.textContent = localizedAlertRuleTitle(alert);
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
    if (!Object.prototype.hasOwnProperty.call(ALERT_RULE_STRINGS, rule)) {
        if (gCurLang !== gLangEn) {
            return getAlertsUiString("msg_generic");
        }
        return alert.message || getAlertsUiString("msg_generic");
    }
    const msgKey = "msg_" + rule;
    const localized = getAlertsUiString(msgKey);
    if (localized !== msgKey) {
        if (rule === "battery_low_soc") {
            if (d.soc_percent == null || d.soc_percent === "") {
                return getAlertsUiString("msg_generic");
            }
            return localized.replace("%s", String(d.soc_percent));
        }
        return localized;
    }
    switch (rule) {
        case "battery_low_soc":
            if (d.soc_percent == null || d.soc_percent === "") {
                return getAlertsUiString("msg_generic");
            }
            return getAlertsUiString("msg_battery_low")
                .replace("%s", String(d.soc_percent));
        case "device_unreachable":
            return getAlertsUiString("msg_device_unreachable");
        case "grabber_stale":
            return getAlertsUiString("msg_grabber_stale");
        default:
            return alert.message || getAlertsUiString("msg_generic");
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

function resolvedPageOverlapsCache(cached, page) {
    if (!page.length || !cached.length) {
        return true;
    }
    const pageIds = {};
    for (let i = 0; i < page.length; i++) {
        pageIds[page[i].id] = true;
    }
    for (let j = 0; j < cached.length; j++) {
        if (pageIds[cached[j].id]) {
            return true;
        }
    }
    return false;
}

function dedupeAlertsById(alerts) {
    const seen = new Set();
    const out = [];
    for (const alert of alerts) {
        if (!seen.has(alert.id)) {
            seen.add(alert.id);
            out.push(alert);
        }
    }
    return out;
}

function resolvedAlertSortTime(alert) {
    return alert.ended_at || alert.started_at || "";
}

function sortResolvedAlertsDesc(alerts) {
    return alerts.slice().sort(function (a, b) {
        const ta = resolvedAlertSortTime(a);
        const tb = resolvedAlertSortTime(b);
        if (ta !== tb) {
            return ta < tb ? 1 : -1;
        }
        return b.id - a.id;
    });
}

function resolvedCursorFromAlert(alert) {
    if (!alert || alert.id == null) {
        return null;
    }
    const ts = resolvedAlertSortTime(alert);
    if (!ts) {
        return null;
    }
    return ts + "," + String(alert.id);
}

function cursorFromResolvedCache(cache) {
    if (!cache || cache.length === 0) {
        return null;
    }
    const sorted = sortResolvedAlertsDesc(cache);
    return resolvedCursorFromAlert(sorted[sorted.length - 1]);
}

function refreshAlertsFetchErrorBanner() {
    const errEl = document.getElementById("alerts_list_error");
    if (errEl && errEl.style.display !== "none") {
        setAlertsListFetchError(true);
    }
}

function setAlertsListFetchError(visible) {
    const errEl = document.getElementById("alerts_list_error");
    if (!errEl) {
        return;
    }
    if (visible) {
        errEl.textContent = getAlertsUiString("fetch_failed");
        errEl.style.display = "block";
    } else {
        errEl.style.display = "none";
    }
}

function refreshAlertsList(options) {
    const reset = Boolean(options && options.reset);
    const append = Boolean(options && options.append);
    if (reset) {
        gResolvedAlertsCache = [];
        gResolvedNextCursor = null;
        gResolvedEndReached = false;
    }
    if (append && !gResolvedNextCursor) {
        return;
    }
    let url = gBaseUrl + "query?type=alerts&status=list"
        + "&resolved_limit=" + String(RESOLVED_PAGE_SIZE);
    if (append && gResolvedNextCursor) {
        url += "&resolved_cursor=" + encodeURIComponent(gResolvedNextCursor);
    }
    return fetchApiJson(url).then(function (result) {
        if (!result.ok || !result.data || result.data.state !== "ok") {
            setAlertsListFetchError(true);
            renderAlertsListDom(
                gLastOpenAlertsCache, gResolvedAlertsCache, true);
            return;
        }
        setAlertsListFetchError(false);
        const openAlerts = result.data.open_alerts || [];
        gLastOpenAlertsCache = openAlerts.slice();
        const resolvedPage = result.data.recent_resolved || [];
        const prevHasMore = gResolvedAlertsHasMore;
        if (append) {
            gResolvedAlertsCache = sortResolvedAlertsDesc(dedupeAlertsById(
                gResolvedAlertsCache.concat(resolvedPage)));
            gResolvedNextCursor = result.data.next_resolved_cursor || null;
            if (!gResolvedNextCursor && result.data.resolved_has_more) {
                gResolvedNextCursor = cursorFromResolvedCache(
                    gResolvedAlertsCache);
            }
            gResolvedAlertsHasMore = Boolean(result.data.resolved_has_more);
            if (!gResolvedAlertsHasMore && !gResolvedNextCursor) {
                gResolvedEndReached = true;
            }
        } else if (reset) {
            gResolvedAlertsCache = sortResolvedAlertsDesc(resolvedPage.slice());
            gResolvedNextCursor = result.data.next_resolved_cursor || null;
            gResolvedAlertsHasMore = Boolean(result.data.resolved_has_more);
        } else {
            if (gResolvedAlertsCache.length
                && !resolvedPageOverlapsCache(
                    gResolvedAlertsCache, resolvedPage)) {
                gResolvedAlertsCache = sortResolvedAlertsDesc(
                    resolvedPage.slice());
                gResolvedNextCursor = result.data.next_resolved_cursor || null;
                gResolvedAlertsHasMore = Boolean(
                    result.data.resolved_has_more);
                gResolvedEndReached = false;
            } else {
                gResolvedAlertsCache = sortResolvedAlertsDesc(dedupeAlertsById(
                    resolvedPage.concat(gResolvedAlertsCache)));
                if (gResolvedAlertsCache.length > resolvedPage.length) {
                    gResolvedNextCursor = cursorFromResolvedCache(
                        gResolvedAlertsCache);
                    gResolvedAlertsHasMore = gResolvedEndReached
                        ? false
                        : (Boolean(result.data.resolved_has_more)
                            || prevHasMore);
                } else {
                    gResolvedNextCursor = (
                        result.data.next_resolved_cursor || null);
                    gResolvedAlertsHasMore = gResolvedEndReached
                        ? false
                        : Boolean(result.data.resolved_has_more);
                }
            }
        }
        renderAlertsListDom(openAlerts, gResolvedAlertsCache, false);
        const moreWrap = document.getElementById("alerts_load_more_wrap");
        const moreBtn = document.getElementById("alerts_load_more_btn");
        if (moreWrap) {
            setElementVisible("alerts_load_more_wrap", gResolvedAlertsHasMore);
        }
        if (moreBtn && !moreBtn.dataset.bound) {
            moreBtn.dataset.bound = "1";
            moreBtn.onclick = function () {
                refreshAlertsList({ append: true });
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
        refreshAlertsList({});
    }).catch(function () {
        if (errEl) {
            errEl.textContent = getAlertsUiString("ack_failed");
            errEl.style.display = "block";
        }
    });
}
