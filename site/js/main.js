// This base URL is used as the destination for REST query calls
var gBaseUrl = "";

// Global status flag
var gDashboardVisible = false;


// History types
const histories = {
    TODAY: 'today',
    DAY: 'day',
    MONTH: 'month',
    YEAR: 'year',
    ALL: 'all'
}

let gCurHistory = histories.DAY;

let gCurDate = new Date();
let gMinDate = null

let gDahboardGraphTimespan = 24

/** Incremented on every navigation; guards async view setup after slow API calls. */
let gViewGeneration = 0;

function bumpViewGeneration() {
    gViewGeneration += 1;
    return gViewGeneration;
}

// Called when index.html has finished loading
window.addEventListener('DOMContentLoaded', event => {
    gBaseUrl = resolveApiBaseUrl();
    console.log("Setting base URI to " + gBaseUrl);
    restoreSettings();
    updateDashboardTimeSpanButtons();
    showViewDashboard();
    restoreLanguage();
    updateTime();
    ensureInstanceCalendarLoaded().then(function () {
        updateTime();
        updateDashboardEmptyStateFromDates();
    });
    setInterval(updateTime, 1000);
    setInterval(refreshInstanceClockAndCalendar, 3000);
    setInterval(updateRealTimeGraph, 5000);
    setInterval(updateForecastDashboard, 60000);
    setInterval(updateAlertsBadge, 30000);
    refreshInstanceClockAndCalendar();
    updateRealTimeGraph();
    updateForecastDashboard();
    updateAlertsBadge();
    initSelectionBoxes();
    updateCsvDateSelector();
    setVersion();
    setName();
});

function formatInstanceLabel(name) {
    if (typeof name !== "string") {
        return "StrataSolar";
    }
    const trimmed = name.trim();
    if (trimmed.length === 0) {
        return "StrataSolar";
    }
    if (trimmed.toLowerCase().includes("stratasolar")) {
        return trimmed;
    }
    return "StrataSolar · " + trimmed;
}

let gStatsBestYearDate = null;

function isViewVisible(viewId) {
    const element = document.getElementById(viewId);
    if (element == null) {
        return false;
    }
    return window.getComputedStyle(element).display !== "none";
}

function refreshLocaleDependentViews() {
    if (isViewVisible("view_history")) {
        document.getElementById("headline_history").textContent = getHistoryHeadlineForMode(gCurHistory);
        updateHistoryStats();
    }
    if (isViewVisible("view_statistics")) {
        if (gStatsBestYearDate != null) {
            document.getElementById("stats_best_year_date").textContent =
                formatStatsBestYearDate(gStatsBestYearDate);
        }
        updateStatistics();
    }
    if (gDashboardVisible) {
        updateCurrentStats();
        updateRealTimeGraph();
        updateForecastDashboard();
    }
    if (gAlertsViewVisible) {
        if (typeof refreshAlertsFetchErrorBanner === "function") {
            refreshAlertsFetchErrorBanner();
        }
        gLastAlertsRenderKey = "";
        refreshAlertsList();
        updateAlertsBadge();
    } else {
        updateAlertsBadge();
    }
}

function getHistoryHeadlineForMode(mode) {
    switch (mode) {
        case histories.TODAY:
        case histories.DAY:
            return getHistoryString("daily_data");
        case histories.MONTH:
            return getHistoryString("monthly_data");
        case histories.YEAR:
            return getHistoryString("yearly_data");
        case histories.ALL:
            return getHistoryString("all_time_data");
        default:
            return getHistoryString("daily_data");
    }
}

function setName() {
    fetchNameJSON().then(name => {
        const label = formatInstanceLabel(name);
        const el = document.getElementById("instance-name");
        el.textContent = label;
        el.title = label;
        document.title = label;
    })
}

  async function fetchNameJSON() {
    const response = await fetch(gBaseUrl + 'name');
    const name = await response.json();
    return name;
}

function restoreSettings() {
    var ts = localStorage.getItem("dash_time_span");
    if (ts != null) {
        gDahboardGraphTimespan = normalizeDashboardHours(ts);
        if (String(gDahboardGraphTimespan) !== ts) {
            localStorage.setItem("dash_time_span", String(gDahboardGraphTimespan));
        }
    }
}

function setDashboardNoDataVisible(visible) {
    setElementVisible("row_dashboard_no_data", visible);
}

function setDashboardChartEmptyVisible(visible) {
    setElementVisible("dashboard_chart_empty", visible);
}

const DASH_STAT_VALUE_IDS = [
    "dash_today_produced", "dash_today_consumed", "dash_today_fed_in",
    "dash_today_earned", "dash_today_autarky",
    "dash_all_time_produced", "dash_all_time_consumed", "dash_all_time_fed_in",
    "dash_all_time_earned", "dash_all_time_autarky",
];

function setDashboardStatPlaceholders() {
    for (const id of DASH_STAT_VALUE_IDS) {
        document.getElementById(id).textContent = "—";
    }
}

function updateDashboardEmptyStateFromDates() {
    if (!gDashboardVisible) {
        return;
    }
    if (!instanceDatabaseHasData()) {
        setDashboardNoDataVisible(true);
        setDashboardStatPlaceholders();
        updateInfoGraphic(0, 0, 0);
    }
}

function handleReferenceTodayChange(previousYmd) {
    const nextYmd = gReferenceTodayYmd;
    if (!nextYmd || previousYmd === nextYmd) {
        return Promise.resolve();
    }
    const previousYear = previousYmd ? previousYmd.slice(0, 4) : null;
    const nextYear = nextYmd.slice(0, 4);
    const previousMonth = previousYmd ? previousYmd.slice(0, 7) : null;
    const nextMonth = nextYmd.slice(0, 7);

    function resyncSelections() {
        if (gCurHistory === histories.TODAY) {
            selectDate(getReferenceTodayDate());
        } else {
            selectDate(clampDateToInstanceBounds(gCurDate));
        }
        if (!gDashboardVisible && gCurHistory !== histories.ALL) {
            updateHistoryStats();
        }
        updateDashboardEmptyStateFromDates();
        if (gDashboardVisible && typeof updateForecastDashboard === "function") {
            updateForecastDashboard();
        }
    }

    if (previousYear !== nextYear) {
        return reloadInstanceDatesPayload().then(function () {
            resyncSelections();
        });
    }
    if (previousMonth !== nextMonth) {
        resyncSelections();
    } else {
        resyncSelections();
    }
    return Promise.resolve();
}

function applyDashboardFromCurrentResult(result) {
    const subtitleTime = formatInstanceClockText(getLocale());
    document.getElementById("dashboard_subtitle_time").textContent =
        subtitleTime || "";

    if (!instanceDatabaseHasData()) {
        setDashboardNoDataVisible(true);
        setDashboardStatPlaceholders();
        updateInfoGraphic(0, 0, 0);
        return;
    }

    if (!isApiSuccess(result)) {
        setDashboardNoDataVisible(true);
        setDashboardStatPlaceholders();
        updateInfoGraphic(0, 0, 0);
        return;
    }
    setDashboardNoDataVisible(false);
    const stats = result.data;

    document.getElementById("dash_today_produced").innerHTML = numFormat(safeNumber(stats["today_produced_kwh"]) * 1000.0, 0);
    document.getElementById("dash_today_consumed").innerHTML = numFormat(safeNumber(stats["today_consumed_kwh"]) * 1000.0, 0);
    document.getElementById("dash_today_fed_in").innerHTML = numFormat(safeNumber(stats["today_fed_in_kwh"]) * 1000.0, 0);
    document.getElementById("dash_today_earned").innerHTML = numFormat(safeNumber(stats["today_earned"]), 2);
    document.getElementById("dash_today_autarky").innerHTML = numFormat(safeNumber(stats["today_autarky"]), 0);

    document.getElementById("dash_all_time_produced").innerHTML = numFormat(safeNumber(stats["all_time_produced_kwh"]), 0);
    document.getElementById("dash_all_time_consumed").innerHTML = numFormat(safeNumber(stats["all_time_consumed_kwh"]), 0);
    document.getElementById("dash_all_time_fed_in").innerHTML = numFormat(safeNumber(stats["all_time_fed_in_kwh"]), 0);
    document.getElementById("dash_all_time_earned").innerHTML = numFormat(safeNumber(stats["all_time_earned"]), 2);
    document.getElementById("dash_all_time_autarky").innerHTML = numFormat(safeNumber(stats["all_time_autarky"]), 0);

    updateInfoGraphic(
        Math.floor(safeNumber(stats["currently_produced_w"])),
        Math.floor(safeNumber(stats["currently_consumed_grid_w"])),
        Math.floor(safeNumber(stats["currently_fed_in_w"])));
}

/** Refresh instance `today` and clock fields even when the Dashboard is hidden. */
function refreshInstanceClockAndCalendar() {
    return fetchCurrentStatsJSON().then(function (result) {
        const previousYmd = gReferenceTodayYmd;
        if (isApiSuccess(result)) {
            applyInstanceClockFields(result.data);
            updateTime();
            return handleReferenceTodayChange(previousYmd).then(function () {
                if (gDashboardVisible) {
                    applyDashboardFromCurrentResult(result);
                }
            });
        }
        if (gDashboardVisible) {
            applyDashboardFromCurrentResult(result);
        }
    });
}

// Called cyclically to update the current stats (dashboard view only)
function updateCurrentStats() {
    if (!gDashboardVisible) {
        return;
    }
    refreshInstanceClockAndCalendar();
}

// Called cyclically to update the time
function updateTime() {
    const locale = getLocale();
    const el = document.getElementById("time");
    const instanceClock = formatInstanceClockTime(locale);
    if (instanceClock) {
        el.textContent = instanceClock.tzLabel
            ? instanceClock.timeText + " " + instanceClock.tzLabel
            : instanceClock.timeText;
        return;
    }
    el.textContent = "";
}

// Async function to get the current stats
async function fetchCurrentStatsJSON() {
    return fetchApiJson(gBaseUrl + "query?type=current");
}

// Called cyclically to update the current stats
function updateRealTimeGraph() {
    if (!gDashboardVisible) return;
    fetchRealTimeStatsJSON().then(result => {
        const rows = isApiSuccess(result) && Array.isArray(result.data) ? result.data : [];
        const hasPoints = rows.length > 0;
        setDashboardChartEmptyVisible(!hasPoints);
        createDashboardChart("chart_dashboard", rows);
    });
}

// Async function to get the real time stats
async function fetchRealTimeStatsJSON() {
    const h = normalizeDashboardHours(gDahboardGraphTimespan);
    return fetchApiJson(gBaseUrl + "query?type=real_time&h=" + h);
}

function initSelectionBoxes() {
    // Days: numbers 1 to 31
    for (let i = 1; i <= 31; i++) {
        addSelectionItem("selection_day2", i.toString(), i.toString());
        addSelectionItem("csv_selection_day2", i.toString(), i.toString());
    }
    ensureInstanceCalendarLoaded().then(function (ok) {
        if (!ok || !gDatesPayload) {
            selectDate(getReferenceTodayDate());
            return;
        }
        const dates = gDatesPayload;
        const yearMin = dates["year_min"];
        const yearMax = dates["year_max"];
        if (yearMin == null || yearMax == null) {
            selectDate(getReferenceTodayDate());
            updateDashboardEmptyStateFromDates();
            return;
        }
        rebuildYearSelectOptionsFromDates();
        selectDate(getReferenceTodayDate());
        updateDashboardEmptyStateFromDates();
    });
}

function selectDate(date) {
    date = clampDateToInstanceBounds(date);
    gCurDate = date;
    const year = date.getFullYear();
    ensureYearOptionInSelect("selection_year2", year);
    ensureYearOptionInSelect("csv_selection_year2", year);
    // Combo boxes 1
    document.getElementById('selection_year2').value = String(year);
    document.getElementById('selection_month2').value = date.getMonth() + 1;
    document.getElementById('selection_day2').value = date.getDate();
    // Combo boxes 2
    document.getElementById('csv_selection_year2').value = String(year);
    document.getElementById('csv_selection_month2').value = date.getMonth() + 1;
    document.getElementById('csv_selection_day2').value = date.getDate();
}

// Async function to get the important dates
async function fetchDatesJSON() {
    return fetchApiJson(gBaseUrl + "query?type=dates");
}


// Called cyclically to update the current stats
function updateHistoryStats() {
    if (gCurHistory !== histories.ALL && !historyYearSelectReady()) {
        setElementVisible("row_error_banner", true);
        setElementVisible("row_history_data", false);
        setElementVisible("history_card_high_res", false);
        return;
    }
    // Store data
    let year = document.getElementById('selection_year2').value.toString();
    let month = document.getElementById('selection_month2').value.toString();
    let day = document.getElementById('selection_day2').value.toString();
    gCurDate = parseYmd(year + "-" + padStr(month) + "-" + padStr(day));
    // Update stats
    fetchHistoryStatsJSON().then(result => {
        const stats = result.data;
        if (isApiSuccess(result) && stats["state"] == "ok") {
            setElementVisible("row_error_banner", false);
            setElementVisible("row_history_data", true);
            setElementVisible("history_card_high_res", true);   

            document.getElementById("history_stat_produced").innerHTML = numFormat(stats["produced_kwh"], 2);

            document.getElementById("history_stat_self_consumed").innerHTML = numFormat(stats["consumed_from_pv_kwh"], 2);
            document.getElementById("history_stat_fedin").innerHTML = numFormat(stats["usage_fed_in_kwh"], 2);

            document.getElementById("history_stat_consumption_grid").innerHTML = numFormat(stats["consumed_from_grid_kwh"], 2);
            document.getElementById("history_stat_consumption_self").innerHTML = numFormat(stats["consumed_from_pv_kwh"], 2);
            document.getElementById("history_stat_consumption_total").innerHTML = numFormat(stats["consumed_total_kwh"], 2);

            document.getElementById("history_stat_earned_feedin").innerHTML = numFormat(stats["earned_feedin"], 2);
            document.getElementById("history_stat_earned_self").innerHTML = numFormat(stats["earned_savings"], 2);
            document.getElementById("history_stat_earned_total").innerHTML = numFormat(stats["earned_total"], 2);

            document.getElementById("history_stat_autarky").innerHTML = numFormat(stats["autarky"], 0);

            // Create the consumption doughnut chart
            createConsumptionChart(
                "chart_consumption",
                safeNumber(stats["consumed_from_grid_percent"]),
                safeNumber(stats["consumed_from_pv_percent"]));

            createUsageChart(
                "chart_usage",
                safeNumber(stats["usage_fed_in_percent"]),
                safeNumber(stats["usage_self_consumed_percent"]));

            // Create high res chart
            if (stats["high_res"] != "") {
                try {
                    const hrData = JSON.parse(stats["high_res"]);
                    createHighResChart("chart_history_high_res", hrData);
                    setElementVisible("history_card_high_res", true);
                } catch (parseError) {
                    console.warn("Invalid high_res payload", parseError);
                    setElementVisible("history_card_high_res", false);
                }
            } else {
                setElementVisible("history_card_high_res", false);
            }
        }
        else {
            setElementVisible("row_error_banner", true);
            setElementVisible("row_history_data", false);
            setElementVisible("history_card_high_res", false);
        }
    });

    // Also update the details graph
    if (gCurHistory == histories.MONTH || gCurHistory == histories.YEAR || gCurHistory == histories.ALL) {
        if (gCurHistory === histories.ALL || historyYearSelectReady()) {
            updateHistoryDetailsGraphs();
        }
    }
}

// Async function to get the current stats
async function fetchHistoryStatsJSON() {
    // Build query
    let query = "query?type=historical&table=";
    switch (gCurHistory) {
        case histories.TODAY:
        case histories.DAY:
            query += "days&date=";
            query += document.getElementById('selection_year2').value.toString();
            query += "-";
            query += padStr(document.getElementById('selection_month2').value.toString());
            query += "-";
            query += padStr(document.getElementById('selection_day2').value.toString());
            break;
        case histories.MONTH:
            query += "months&date=";
            query += document.getElementById('selection_year2').value.toString();
            query += "-";
            query += padStr(document.getElementById('selection_month2').value.toString());
            break;
        case histories.YEAR:
            query += "years&date=";
            query += document.getElementById('selection_year2').value.toString();
            break;
        case histories.ALL:
            query += "all_time&date=all_time";
            break;
    }
    //console.log("Refreshing historic stats: " + query);
    return fetchApiJson(gBaseUrl + query);
}

function updateHistoryDetailsGraphs() {
    if (gCurHistory !== histories.ALL && !historyYearSelectReady()) {
        return;
    }
    fetchHistoryDetailsJSON().then(result => {
        const stats = isApiSuccess(result) && Array.isArray(result.data) ? result.data : [];
        createHistoryDetailsChartProduction("chart_history_details_production", stats);
        createHistoryDetailsChartConsumption("chart_history_details_consumption", stats);
    });
}

// Async function to get the current stats
async function fetchHistoryDetailsJSON() {
    // Build query
    let query = "query?type=";
    switch (gCurHistory) {
        case histories.MONTH:
            query += "days_in_month&date=";
            query += document.getElementById('selection_year2').value.toString();
            query += "-";
            query += padStr(document.getElementById('selection_month2').value.toString());
            break;
        case histories.YEAR:
            query += "months_in_year&date=";
            query += document.getElementById('selection_year2').value.toString();
            break;
        case histories.ALL:
            query += "years_in_all_time";
            break;
    }
    return fetchApiJson(gBaseUrl + query);
}

function setStatsHeadlineTile(elementId, formattedValue, unit) {
    const unitMarkup = unit
        ? ' <span class="stats-tile-unit">' + unit + "</span>"
        : "";
    document.getElementById(elementId).innerHTML =
        '<span class="stats-tile-number">' + formattedValue + "</span>" + unitMarkup;
}

function updateStatistics() {
    fetchStatisticsJSON().then(result => {
        if (!isApiSuccess(result)) {
            return;
        }
        const stats = result.data;
        if (stats["state"] == "ok") {
            setStatsHeadlineTile(
                "stats_highest_prod_value",
                numFormat(stats["highest_production_w"], 0),
                "W");
            document.getElementById("stats_highest_prod_date").innerHTML = prettyPrintDateString(stats["highest_production_date"]);

            setStatsHeadlineTile(
                "stats_best_day_value",
                numFormat(stats["best_day_production_kwh"], 2),
                "kWh");
            document.getElementById("stats_best_day_date").innerHTML = prettyPrintDateString(stats["best_day_date"]);

            setStatsHeadlineTile(
                "stats_best_month_value",
                numFormat(stats["best_month_production_kwh"], 2),
                "kWh");
            document.getElementById("stats_best_month_date").innerHTML = prettyPrintDateStringWithoutDay(stats["best_month_date"]);

            setStatsHeadlineTile(
                "stats_best_year_value",
                numFormat(stats["best_year_production_kwh"], 2),
                "kWh");
            gStatsBestYearDate = stats["best_year_date"];
            document.getElementById("stats_best_year_date").textContent =
                formatStatsBestYearDate(gStatsBestYearDate);

            document.getElementById("statistics_value_avg_daily_prod").innerHTML = numFormat(stats["average_daily_production_kwh"], 2);

            document.getElementById("statistics_value_start_date").innerHTML = prettyPrintDateString(stats["start_of_operation"]);
            document.getElementById("statistics_value_runtime").innerHTML = stats["days_of_operation"] + " " + getUnitDays();
        }
    });
}

// Async function to get the statistics stats
async function fetchStatisticsJSON() {
    return fetchApiJson(gBaseUrl + "query?type=statistics");
}



function showViewDashboard() {
    bumpViewGeneration();
    setElementVisible("view_dashboard", true);
    setElementVisible("view_statistics", false);
    setElementVisible("view_history", false);
    setElementVisible("view_csv", false);
    hideAlertsViewIfNeeded();
    setInfoGraphicEnabled(true);
    gDashboardVisible = true;
    setSidebarActive("dashboard");
    updateForecastDashboard();
}

function showViewStatistics() {
    bumpViewGeneration();
    setElementVisible("view_dashboard", false);
    setElementVisible("view_statistics", true);
    setElementVisible("view_history", false);
    setElementVisible("view_csv", false);
    hideAlertsViewIfNeeded();
    setInfoGraphicEnabled(false);
    gDashboardVisible = false;
    setSidebarActive("statistics");
    updateStatistics();
}

function showViewHistory(mode) {
    const viewGen = bumpViewGeneration();
    setElementVisible("view_dashboard", false);
    setElementVisible("view_statistics", false);
    setElementVisible("view_history", true);
    setElementVisible("view_csv", false);
    hideAlertsViewIfNeeded();
    setInfoGraphicEnabled(false);
    gDashboardVisible = false;
    gCurHistory = mode;

    const openHistory = function () {
    switch (mode) {
        case histories.TODAY:
            selectDate(getReferenceTodayDate());
            document.getElementById("headline_history").textContent = getHistoryString("daily_data");
            setElementVisible("selection_prev", true);
            setElementVisible("selection_next", true);
            setElementVisible("selection_year", true);
            setElementVisible("selection_month", true);
            setElementVisible("selection_day", true);
            setElementVisible("history_card_graphs", false);
            setElementVisible("history_card_high_res", true);
        case histories.DAY:
            document.getElementById("headline_history").textContent = getHistoryString("daily_data");
            setElementVisible("selection_prev", true);
            setElementVisible("selection_next", true);
            setElementVisible("selection_year", true);
            setElementVisible("selection_month", true);
            setElementVisible("selection_day", true);
            setElementVisible("history_card_graphs", false);
            setElementVisible("history_card_high_res", true);
            break;
        case histories.MONTH:
            document.getElementById("headline_history").textContent = getHistoryString("monthly_data");
            setElementVisible("selection_prev", true);
            setElementVisible("selection_next", true);
            setElementVisible("selection_year", true);
            setElementVisible("selection_month", true);
            setElementVisible("selection_day", false);
            setElementVisible("history_card_high_res", false);
            // Show the days
            setElementVisible("history_card_graphs", true);
            break;
        case histories.YEAR:
            document.getElementById("headline_history").textContent = getHistoryString("yearly_data");
            setElementVisible("selection_prev", true);
            setElementVisible("selection_next", true);
            setElementVisible("selection_year", true);
            setElementVisible("selection_month", false);
            setElementVisible("selection_day", false);
            setElementVisible("history_card_high_res", false);
            // Show the months
            setElementVisible("history_card_graphs", true);
            break;
        case histories.ALL:
            document.getElementById("headline_history").textContent = getHistoryString("all_time_data");
            setElementVisible("selection_prev", false);
            setElementVisible("selection_next", false);
            setElementVisible("selection_year", false);
            setElementVisible("selection_month", false);
            setElementVisible("selection_day", false);
            setElementVisible("history_card_high_res", false);
            // Show the years
            setElementVisible("history_card_graphs", true);
            break;
    }
    setSidebarActive(gCurHistory);
    updateHistoryStats();
    };
    refreshInstanceClockAndCalendar().then(function () {
        if (viewGen !== gViewGeneration) {
            return;
        }
        openHistory();
    });
}

function showViewCsv() {
    bumpViewGeneration();
    setElementVisible("view_dashboard", false);
    setElementVisible("view_statistics", false);
    setElementVisible("view_history", false);
    setElementVisible("view_csv", true);
    hideAlertsViewIfNeeded();
    setInfoGraphicEnabled(false);
    gDashboardVisible = false;
    setSidebarActive("csv");
}

function updateCsvDateSelector() {
    if (document.getElementById("csv_range_rad_day").checked == true) {
        setElementVisible("csv_selection_year", true);
        setElementVisible("csv_selection_month", true);
        setElementVisible("csv_selection_day", true);

        setElementEnabled("csv_res_rad_day", true);
        setElementEnabled("csv_res_rad_month", false);
        setElementEnabled("csv_res_rad_year", false);

        if (isElementChecked("csv_res_rad_month") || isElementChecked("csv_res_rad_year"))
            setElementChecked("csv_res_rad_day", true);
    }
    else if (document.getElementById("csv_range_rad_month").checked == true) {
        setElementVisible("csv_selection_year", true);
        setElementVisible("csv_selection_month", true);
        setElementVisible("csv_selection_day", false);

        setElementEnabled("csv_res_rad_day", true);
        setElementEnabled("csv_res_rad_month", false);
        setElementEnabled("csv_res_rad_year", false);

        if (isElementChecked("csv_res_rad_month") || isElementChecked("csv_res_rad_year"))
            setElementChecked("csv_res_rad_day", true);
    }
    else if (document.getElementById("csv_range_rad_year").checked == true) {
        setElementVisible("csv_selection_year", true);
        setElementVisible("csv_selection_month", false);
        setElementVisible("csv_selection_day", false);

        setElementEnabled("csv_res_rad_day", true);
        setElementEnabled("csv_res_rad_month", true);
        setElementEnabled("csv_res_rad_year", false);

        if (isElementChecked("csv_res_rad_year"))
            setElementChecked("csv_res_rad_month", true);
    }
    else {
        setElementVisible("csv_selection_year", false);
        setElementVisible("csv_selection_month", false);
        setElementVisible("csv_selection_day", false);

        setElementEnabled("csv_res_rad_day", true);
        setElementEnabled("csv_res_rad_month", true);
        setElementEnabled("csv_res_rad_year", true);
    }
}


function datePrev() {
    let date = new Date(gCurDate)
    if (gCurHistory == histories.DAY || gCurHistory == histories.TODAY) {
        date.setDate(date.getDate() - 1);
    }
    else if (gCurHistory == histories.MONTH) {
        date.setMonth(date.getMonth() - 1);
    }
    else if (gCurHistory == histories.YEAR) {
        date.setFullYear(date.getFullYear() - 1);
    }

    if (date < gMinDate) date = new Date(gMinDate);

    selectDate(date);
    updateHistoryStats();
}

function dateNext() {
    const viewGen = gViewGeneration;
    refreshInstanceClockAndCalendar().then(function () {
        if (viewGen !== gViewGeneration) {
            return;
        }
        let date = new Date(gCurDate);
        if (gCurHistory == histories.DAY || gCurHistory == histories.TODAY) {
            date.setDate(date.getDate() + 1);
        }
        else if (gCurHistory == histories.MONTH) {
            date.setMonth(date.getMonth() + 1);
        }
        else if (gCurHistory == histories.YEAR) {
            date.setFullYear(date.getFullYear() + 1);
        }

        const maxDate = getReferenceTodayDate();
        if (date > maxDate) date = new Date(maxDate);

        selectDate(date);
        updateHistoryStats();
    });
}

function changeDashboardGraphTimeSpan(hours) {
    gDahboardGraphTimespan = normalizeDashboardHours(hours);
    localStorage.setItem("dash_time_span", String(gDahboardGraphTimespan));
    updateDashboardTimeSpanButtons();
    updateRealTimeGraph();
}

function updateDashboardTimeSpanButtons() {
    [2, 4, 12, 24].forEach(hours => {
        const btn = document.getElementById("dash_timespan_" + hours);
        if (!btn) {
            return;
        }
        const selected = gDahboardGraphTimespan === hours;
        btn.setAttribute("aria-pressed", selected ? "true" : "false");
    });
}

function setElementVisible(name, visible) {
    document.getElementById(name).style.display = visible ? 'block' : 'none';
}

function setElementEnabled(name, enabled) {
    if (enabled)
        document.getElementById(name).removeAttribute("disabled");
    else
        document.getElementById(name).setAttribute("disabled", "");
}

function isElementChecked(name) {
    return document.getElementById(name).checked;
}

function setElementChecked(name, checked) {
    document.getElementById(name).checked = checked;
}

function addSelectionItem(control, name, value) {
    const node = document.createElement("option");
    node.setAttribute("value", value);
    const textnode = document.createTextNode(name);
    node.appendChild(textnode);
    document.getElementById(control).appendChild(node);
}

function padStr(i) {
    return (i < 10) ? "0" + i : "" + i;
}
