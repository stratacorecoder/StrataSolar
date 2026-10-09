# Forecasting and operational alerts

StrataSolar can forecast near-term PV production (and consumption from weekday history) and raise debounced operational alerts in the UI. Both features are optional and degrade gracefully when data or network is missing.

Forecast fetches run in a background worker (single-flight: at most one Open-Meteo refresh at a time). Each refresh uses `forecast.open_meteo_timeout_s` (default **15 s**, range 3–60) as one wall-clock budget for the forecast API call and the calibration archive call combined. Failed or history-fallback refreshes retry after 2 / 5 / 15 / 30 minutes before returning to `refresh_interval_s`. Process shutdown does not wait for in-flight fetches beyond a short join. The grabber sampling loop and HTTP GET handlers only read SQLite (cache or `unavailable` / `pending`); they never call Open-Meteo from request handlers. Alert evaluation that may write state runs in the grabber loop and in a server background thread (`grabber_stale` only)—not in GET handlers.

## Forecasting

### How it works

1. **Weather-based (preferred)** when `forecast.latitude` and `forecast.longitude` are set: hourly global tilted irradiance from [Open-Meteo](https://open-meteo.com/) is converted to kWh using `panel_capacity_kw`, tilt, compass azimuth (`panel_azimuth_deg`, 180 = south), and `system_loss_factor`. Values are converted to Open-Meteo’s convention (0 = south) before API calls.
2. **Calibration**: for the last `history_days_calibration` complete days, predicted vs actual production yields a median scale factor (clamped 0.5–2.0) applied to future weather forecasts.
3. **History fallback** when coordinates are missing or Open-Meteo fails: weekday averages from the last `history_days_fallback` days, with a smooth intraday curve.
4. **Fresh installs**: until `min_history_days` day rows exist, the API returns `state: insufficient_history`.

The grabber schedules a background refresh every `refresh_interval_s` (default 3600 s); results are cached in SQLite (`forecast_cache`). Yesterday’s predicted vs actual values are stored in `forecast_accuracy` when possible (recorded before the refresh when the local day rolls over).

### Configuration

See commented blocks in `templates/config.yml`. Minimum useful setup for weather forecasts:

```yaml
forecast:
  enabled: true
  latitude: 52.52
  longitude: 13.41
  panel_capacity_kw: 8.0
  panel_tilt_deg: 30
  panel_azimuth_deg: 180
```

### API

- `GET /query?type=forecast` — forecast payload + recent accuracy rows
- `GET /query?type=forecast_accuracy` — accuracy history only

### Real hardware checks

- Confirm latitude/longitude and `panel_capacity_kw` match the site.
- After a few sunny days, compare dashboard “Forecast today” vs “Actual so far” and review accuracy in the API.
- Disconnect WAN briefly: recording and dashboard must stay up; forecast may show history-only or unavailable.

## Operational alerts

Alerts are evaluated in the grabber (default every 60 s) and `grabber_stale` is also checked from the web server using the loop heartbeat. Stored in `alerts` and listed in the UI. One ongoing condition yields one open alert; it resolves after the condition has been clear for `resolve_clear_minutes`.

Open alerts for rule IDs that are no longer evaluated (for example after an upgrade) are auto-resolved on the next evaluation or schema ensure; their rule state is cleared. On every schema ensure, **all** pending `notification_outbox` rows are deleted. The outbox table may remain in older databases but is not used for sending in this release.

| Rule ID | Default severity | Condition (summary) |
|--------|------------------|---------------------|
| `device_unreachable` | critical | No device success heartbeat within `max(device_stale_min_s, device_stale_multiplier × grabber.interval_s)`. With forecast coordinates: on typical days, suppressed when the sun is below `daylight_sun_elevation_deg` (plus `device_unreachable_sunrise_grace_minutes`). **Low-sun days** (max elevation that day stays below that threshold): the inverter is only expected online while the sun is above **0°** (same grace after 0° is crossed upward); if the sun never rises above 0° that day, suppression applies all day (no nightly criticals on a sleeping inverter). Set `device_unreachable_night_suppress: false` for always-on inverters (e.g. hybrids that never sleep); `grabber_stale` still alerts regardless. **Midnight sun**: ~60 min suppression after local midnight. No `zero_production` / `battery_stuck` daylight on low-sun days. An already-open outage stays open until the device responds. Without coordinates, optional quiet hours: `device_unreachable_quiet_start_hour` and `device_unreachable_quiet_end_hour` must be set **together**. |
| `grabber_stale` | critical | Grabber loop heartbeat stale (same time limit) |
| `zero_production_daylight` | warning | **On automatically** when `forecast.latitude` / `longitude` are set (solar elevation gate; off all day in polar night). Otherwise opt-in via `daylight_rules_enabled` and fixed local hours. Stays open until production is seen again. |
| `production_below_forecast` | warning | After `below_forecast_after_hour`, today’s production &lt; `below_forecast_fraction` of forecast progress (forecast ≥ `below_forecast_min_kwh`) |
| `production_below_baseline` | warning | Today &lt; `baseline_below_fraction` × median daily production for `baseline_consecutive_days` (default **2**) consecutive local days; without lat/lon, intraday checks compare production so far to the median scaled by elapsed day fraction; suppressed when today’s forecast is much lower than the median (cloudy-weather guard) |
| `production_spike` | warning | Today’s production &gt; `spike_multiplier` × median (min `spike_min_delta_kwh`) |
| `consumption_spike` | warning | Today’s consumption &gt; `consumption_spike_multiplier` × recent median (min `consumption_spike_min_kwh`) |
| `battery_low_soc` | warning | `battery_soc_percent` on device ≤ `battery_low_soc_percent` (only if device exposes SOC) |
| `battery_stuck` | info | **On automatically** with lat/lon (same daylight gate as zero production). SOC unchanged &lt; 0.5% for `battery_stuck_minutes`; ignores SOC near 100% or the low-SOC threshold. Stays open until SOC moves. |

Thresholds are under the `alerts:` key in `config.yml` (all optional).

Outbound webhook/SMTP notifications are **not** part of this release; alerts are in-app only.

### API

- `GET /query?type=alerts` — `status=list|open`, `resolved_limit` (≤200), `resolved_cursor` (`ended_at,id` keyset paging; `resolved_offset` is rejected). Polls should refresh open alerts plus the first resolved page only. Invalid parameters return HTTP 400; query failures return `state: error` (not an empty ok).
- `POST /alerts/acknowledge` with `Content-Type: application/json` and body `{"id": <number>}`
- `GET /health` includes `open_alerts` and `forecast_state`

### Dummy fault simulation

```yaml
dummy:
  fault_mode: offline   # or zero_daylight, stale, battery_stuck (off/none/false also mean off)
  battery_soc_percent: 85
```

## Database migration

`ensure_feature_schema()` runs on grabber startup and once when the web server starts (if `data/db.sqlite` exists). GET handlers do not migrate. Safe on existing production databases and fresh installs (uses `schema_meta` like other migrations).

## Known limitations

- **Baseline without lat/lon:** `production_below_baseline` uses a 2-day streak and scales the median by elapsed day fraction; very noisy or partial-day data can still be sensitive compared to weather-gated sites with coordinates.
- **Low-sun lag:** On days when the sun briefly rises above 0°, `device_unreachable` can open shortly after the grace window if the device was offline during that window.
- **Sleeping inverters below +1°:** Devices that only wake when the sun is clearly up may still get brief `device_unreachable` windows on low-sun days when modeled elevation is between 0° and about +1°.
- **Short sun days:** On days with only a few minutes above 0°, outage detection can lag until after the sunrise grace.
- **Polar night:** With no sun above 0°, `device_unreachable` and daylight production rules stay suppressed; a device offline all winter is only surfaced by `grabber_stale` if the grabber loop itself stops updating.
- **Open-Meteo timeout:** `forecast.open_meteo_timeout_s` (default 15, range 3–60) is a single wall-clock budget for the forecast API call plus the calibration archive call in one refresh.
- **Docker compose:** A stock `docker-compose` checkout may not ship `config.yml`; copy from `templates/config.yml` before first run.
