// Shared REST helpers and date utilities for the StrataSolar UI.

const DASHBOARD_GRAPH_HOURS = [2, 4, 12, 24];

/** Instance calendar day (YYYY-MM-DD) from API `today`; null until loaded. */
let gReferenceTodayYmd = null;

/** Instance clock metadata (PR #4 / backend); null until loaded from API. */
let gInstanceTimeZone = null;
let gInstanceTimeZoneValid = false;
let gInstanceUtcOffsetMinutes = null;

let gFetchNetworkErrorLogged = false;
let gDatesPayload = null;
let gInstanceCalendarPromise = null;

/**
 * Fetches JSON from the API and returns status metadata (never throws).
 * @returns {{ok: boolean, status: number, data: *}}
 */
async function fetchApiJson(url) {
    try {
        const response = await fetch(url);
        let data = null;
        const contentType = response.headers.get("content-type") || "";
        if (contentType.includes("json")) {
            data = await response.json();
        } else {
            const text = await response.text();
            if (text) {
                try {
                    data = JSON.parse(text);
                } catch (parseError) {
                    console.warn("Non-JSON response from " + url, parseError);
                }
            }
        }
        gFetchNetworkErrorLogged = false;
        return { ok: response.ok, status: response.status, data };
    } catch (error) {
        if (!gFetchNetworkErrorLogged) {
            console.warn("Request failed (network), further errors suppressed until recovery: " + url, error);
            gFetchNetworkErrorLogged = true;
        }
        return { ok: false, status: 0, data: null };
    }
}

/** Directory URL for API calls (ignores page query string). */
function resolveApiBaseUrl() {
    return new URL(".", document.baseURI).href;
}

function applyInstanceClockFields(data) {
    if (!data || typeof data !== "object") {
        return;
    }
    if (typeof data.today === "string" && /^[0-9]{4}-[0-9]{2}-[0-9]{2}$/.test(data.today)) {
        gReferenceTodayYmd = data.today;
    }
    if (typeof data.time_zone === "string" && data.time_zone.length > 0) {
        gInstanceTimeZone = data.time_zone;
    }
    if (typeof data.time_zone_valid === "boolean") {
        gInstanceTimeZoneValid = data.time_zone_valid;
    }
    if (Number.isFinite(Number(data.utc_offset_minutes))) {
        gInstanceUtcOffsetMinutes = Number(data.utc_offset_minutes);
    }
}

function pad2(n) {
    return n < 10 ? "0" + n : String(n);
}

/** Label for instance zone when IANA/POSIX name is not valid for display. */
function formatUtcOffsetLabel(minutesEast) {
    const sign = minutesEast >= 0 ? "+" : "-";
    const abs = Math.abs(minutesEast);
    const hours = Math.floor(abs / 60);
    const mins = abs % 60;
    return "UTC" + sign + pad2(hours) + ":" + pad2(mins);
}

function getInstanceWallClockParts() {
    if (gInstanceUtcOffsetMinutes == null || !Number.isFinite(gInstanceUtcOffsetMinutes)) {
        return null;
    }
    const totalSeconds = Math.floor(Date.now() / 1000) + gInstanceUtcOffsetMinutes * 60;
    const secondsOfDay = ((totalSeconds % 86400) + 86400) % 86400;
    return {
        hours: Math.floor(secondsOfDay / 3600),
        minutes: Math.floor((secondsOfDay % 3600) / 60),
        seconds: secondsOfDay % 60,
    };
}

function formatInstanceClockTime(locale) {
    const parts = getInstanceWallClockParts();
    if (!parts) {
        return null;
    }
    const wall = new Date(Date.UTC(1970, 0, 1, parts.hours, parts.minutes, parts.seconds));
    const timeText = wall.toLocaleTimeString(locale, {
        timeZone: "UTC",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
    });
    let tzLabel;
    if (gInstanceTimeZoneValid && gInstanceTimeZone) {
        tzLabel = gInstanceTimeZone;
    } else if (gInstanceUtcOffsetMinutes != null) {
        tzLabel = formatUtcOffsetLabel(gInstanceUtcOffsetMinutes);
    } else {
        tzLabel = "";
    }
    return { timeText, tzLabel };
}

function formatInstanceClockText(locale) {
    const clock = formatInstanceClockTime(locale);
    if (!clock) {
        return "";
    }
    return clock.tzLabel ? clock.timeText + " " + clock.tzLabel : clock.timeText;
}

/** True when the response is HTTP-success and body is not an explicit API error/nodata state. */
function isApiSuccess(result) {
    if (!result || !result.ok || result.data == null) {
        return false;
    }
    if (typeof result.data === "object" && !Array.isArray(result.data)) {
        const state = result.data.state;
        if (state === "error" || state === "nodata") {
            return false;
        }
    }
    return true;
}

function safeNumber(value, fallback = 0) {
    const n = Number(value);
    return Number.isFinite(n) ? n : fallback;
}

function formatYmd(date) {
    const y = date.getFullYear();
    const m = padStr(date.getMonth() + 1);
    const d = padStr(date.getDate());
    return y + "-" + m + "-" + d;
}

function parseYmd(ymd) {
    const parts = ymd.split("-");
    if (parts.length !== 3) {
        return new Date();
    }
    return new Date(parseInt(parts[0], 10), parseInt(parts[1], 10) - 1, parseInt(parts[2], 10));
}

function normalizeDashboardHours(hours) {
    const n = parseInt(hours, 10);
    return DASHBOARD_GRAPH_HOURS.includes(n) ? n : 24;
}

function getReferenceTodayDate() {
    if (gReferenceTodayYmd) {
        return parseYmd(gReferenceTodayYmd);
    }
    return parseYmd(formatYmd(new Date()));
}

/** Load instance `today` and clock fields from /query?type=dates (once). */
function ensureInstanceCalendarLoaded() {
    if (!gInstanceCalendarPromise) {
        gInstanceCalendarPromise = fetchApiJson(gBaseUrl + "query?type=dates").then(function (result) {
            if (isApiSuccess(result)) {
                gDatesPayload = result.data;
                applyInstanceClockFields(result.data);
                return true;
            }
            return false;
        });
    }
    return gInstanceCalendarPromise;
}

function formatApiErrorMessage(data) {
    if (data == null) {
        return "";
    }
    if (typeof data === "string") {
        return data;
    }
    if (typeof data.message === "string") {
        return data.message;
    }
    if (typeof data.error === "string") {
        return data.error;
    }
    return "";
}

function historyYearSelectReady() {
    const yearSel = document.getElementById("selection_year2");
    return yearSel != null && yearSel.options.length > 0;
}
