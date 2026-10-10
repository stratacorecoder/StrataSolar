# Forecasting and operational alerts

StrataSolar forecasts near-term PV production for **one site in Bataan, Philippines**, near Balanga City (14.68° N, 120.54° E), and raises debounced equipment alerts for the battery, PV panels, and inverter. Both features are optional and degrade gracefully when data or network is missing. The defaults and replay tests are tuned for Bataan; latitude/longitude remain configurable for the installation's exact position.

Forecast fetches run in a background worker (single-flight: at most one Open-Meteo refresh at a time). One refresh uses a single wall-clock budget `forecast.open_meteo_timeout_s` (default **15 s**, range 3–60) shared by the calibration archive call and the forecast API call. Each HTTP request arms a timer before connect that binds the socket at connect time and calls `socket.shutdown` at expiry (connect, headers, and body); `requests` connect/read timeouts are bounded by the remaining budget. Per-read idle timeout is about **66% of the budget** (at least 5 s within the cap), so time-to-first-byte above that fraction cannot succeed; at the maximum **60 s** budget a silent peer is dropped after about **39 s**. With the default **15 s** budget, a peer that sends nothing for about **10 s to first byte** is treated as down for that refresh. Failed or history-fallback refreshes retry after 2 / 5 / 15 / 30 minutes before returning to `refresh_interval_s`. Process shutdown does not wait for in-flight fetches beyond a short join. The grabber sampling loop and HTTP GET handlers only read SQLite (cache or `unavailable` / `pending`); they never call Open-Meteo from request handlers. Alert evaluation that may write state runs in the grabber loop and in a server background thread (`grabber_stale` only)—not in GET handlers.

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
time_zone: Asia/Manila
forecast:
  enabled: true
  latitude: 14.68
  longitude: 120.54
  panel_capacity_kw: 8.0  # replace with the installed PV rating
  panel_tilt_deg: 15
  panel_azimuth_deg: 180
```

Use south-facing panels (`panel_azimuth_deg: 180`) as the default geometry, then set tilt and azimuth to the actual array. `Asia/Manila` is UTC+8 year-round. Daylight rules use solar elevation at the configured coordinates, so dawn and dusk follow Bataan's seasonal sunrise/sunset rather than European clock hours. The history-only curve uses approximately 06:00–18:00 local time; it is not evidence of clear weather.

### API

- `GET /query?type=forecast` — forecast payload + recent accuracy rows
- `GET /query?type=forecast_accuracy` — accuracy history only

### Real hardware checks

- Confirm latitude/longitude and `panel_capacity_kw` match the site.
- After a few sunny days, compare dashboard “Forecast today” vs “Actual so far” and review accuracy in the API.
- Disconnect WAN briefly: recording and dashboard must stay up; forecast may show history-only or unavailable.

## Operational alerts

### Driver field audit

Audit of **every driver in `backend/devices/`**, before adding equipment rules:

| Driver | Fields exposed to the grabber | Data already fetched but discarded | Unavailable in the current reads |
|--------|-------------------------------|------------------------------------|----------------------------------|
| `Fronius` (Symo/GEN24) | All eight energy/power fields below | Optional `Inverters[*].P` (AC W), `SOC` (%), `Battery_Mode`; `Site.P_Akku` (battery W) in the existing power-flow response | Inverter fault codes, inverter/battery temperature, battery voltage, individual MPPT powers |
| `Sunsynk` / Deye (Solarman or Modbus RTU) | All eight energy/power fields below | Individual MPPT powers from registers **186 / 187**, currently summed | AC output, fault codes, temperatures, battery SOC/power/voltage; no such registers are read |
| `Dummy` | All eight energy/power fields below; optional configured `battery_soc_percent` | None | Hardware diagnostics; any additional readings are explicitly simulated |

The common fields are `total_energy_produced_kwh`, `total_energy_consumed_kwh`, `total_energy_fed_in_kwh`, `current_power_produced_kw`, `current_power_consumed_from_grid_kw`, `current_power_consumed_from_pv_kw`, `current_power_consumed_total_kw`, and `current_power_fed_in_kw`. Totals are kWh and powers are kW. Fronius without a smart meter uses zero meter counters; derived consumption is not independent battery telemetry. Sunsynk reads load directly, but its derived `consumed_from_pv` can include battery supply.

Fronius field semantics are verified against the manufacturer's [Solar API V1 specification, power-flow section](https://www.fronius.com/~/downloads/Solar%20Energy/Operating%20Instructions/42%2C0410%2C2012.pdf): `P_Akku` is negative when charging and positive when discharging; `Inverters[*].P` is AC power; `P_PV` is DC generation on hybrids and AC generation on SnapInverters. Missing/null fields must remain unknown, never be fabricated as fault readings. This release does not add undocumented register reads or additional device requests.

The driver extensions retain these **existing fetched values**:

| Driver | Additional exposed fields | Availability |
|--------|---------------------------|--------------|
| `Fronius` | `inverter_ac_power_kw`, `pv_dc_power_kw`, `battery_soc_percent`, `battery_power_kw`, `battery_mode` | Single-inverter payload only. AC comes from `Inverters[device].P`; DC is identified only on a hybrid (`DT: 99`, battery mode, or SOC plus battery power). SnapInverter `P_PV` is never relabeled as DC. SOC must be finite and within 0–100%; nullable battery power stays unknown. Multiple batteries/inverters are never averaged or paired with aggregate DC power. |
| `Sunsynk` (both transports) | `pv_mppt_power_kw` (two kW readings in register order) | Uses the same reads of 186 / 187. Negative/invalid inputs cannot participate in the imbalance rule. Aggregate PV power preserves the existing signed-sum/clamp behavior. |
| `Dummy` | The same optional fields, including `pv_mppt_power_kw` | Explicit simulations only; battery fault modes supply SOC automatically if it is not configured. |

`device_snapshot.py` copies optional fields from the live driver, including a separate copy of the MPPT list. DB-only snapshots cannot invent AC, MPPT, battery power, temperature, or voltage readings. Stale telemetry pauses equipment checks.

### Weather guards and equipment recovery

At the Bataan coordinates, zero-production and production-underperformance checks require a **fresh Open-Meteo hourly curve for the current Manila day**, generated within twice the refresh interval. History-only, missing, malformed, day-old, and stale weather are unknown conditions. The current hour must predict at least `production_weather_min_fraction × panel_capacity_kw` (default **15%**). If the day's weather forecast is below **55%** of the recent production median, cloudy-day checks are suppressed. Low predicted output on monsoon/typhoon days is therefore suppressed even when the astronomical sun is above the horizon.

Forecast progress uses the sum of completed hourly forecast values plus the elapsed part of the current hour. Baseline progress uses the same daylight fraction; cloudy days break the two-day baseline streak. A 30-minute production debounce and the 45-minute zero-production debounce also reject short cloud dips. Neither the history fallback nor a low-light reading proves that a previously reported fault recovered.

Every new rule has a continuous opening debounce and uses `resolve_clear_minutes` (default **20 minutes**) of healthy observations to resolve. Missing fields, stale reads, nighttime, and weak light where relevant reset pending debounce and **hold** open alerts. Numeric rules use a wider recovery threshold: AC must exceed its zero threshold by 0.1 kW, MPPT peer ratio must recover above its trigger by 0.15, battery SOC must reach 98% to clear a full-charge boundary after a stall, and charging must exceed 0.15 kW to clear an idle boundary. Fault-mode and SOC-jump rules clear after healthy mode/consistent SOC observations for the normal clear period. Battery-low-SOC recovery requires three percentage points above its trigger.

MPPT comparison requires `alerts.panels_mppt_capacity_kw` with one positive capacity for every input, and the strings must have comparable orientation and shading. Powers are normalized by their capacities; a strong peer is the available evidence of good irradiance. Do not enable this comparison for differently oriented/unconnected inputs. The charge-stall rule is **opt-in** (`battery_charge_stalled_enabled: true`) only when the site's charging policy expects PV charging; it requires actual grid export as evidence of surplus and `Battery_Mode: normal`.

Alerts are evaluated in the grabber (default every 60 s) and `grabber_stale` is also checked from the web server using the loop heartbeat. Stored in `alerts` and listed in the UI. One ongoing condition yields one open alert; it resolves after the condition has been clear for `resolve_clear_minutes`.

Every stored/API alert has a `component` field. Existing open and resolved rows are backfilled safely at startup; unknown retired rules are classified as `system`. GET requests can read a legacy schema without migrating it.

| Component | Rules |
|-----------|-------|
| `inverter` | `device_unreachable`, `zero_production_daylight`, `inverter_dc_without_ac` |
| `panels` | `production_below_forecast`, `production_below_baseline`, `panels_mppt_imbalance` |
| `battery` | `battery_low_soc`, `battery_stuck`, `battery_fault`, `battery_soc_jump`, `battery_charge_stalled` |
| `system` | `grabber_stale`, `production_spike`, optional `consumption_spike` |

`consumption_spike` describes usage, not an equipment fault. It is **disabled by default**; opt in with `alerts.consumption_spike_enabled: true`. Turning it off clears a pending condition and resolves an existing alert after the normal clear period.

Open alerts for rule IDs that are no longer evaluated (for example after an upgrade) are auto-resolved on the next evaluation or schema ensure; their rule state is cleared. On every schema ensure, **all** pending `notification_outbox` rows are deleted. The outbox table may remain in older databases but is not used for sending in this release.

| Rule ID | Default severity | Condition (summary) |
|--------|------------------|---------------------|
| `device_unreachable` | critical | Device success heartbeat older than `max(device_stale_min_s, device_stale_multiplier × grabber.interval_s)`; one-minute debounce. Coordinate-based sun gate (+5° by default) and 60-minute sunrise grace suppress sleeping-inverter alerts. Set `device_unreachable_night_suppress: false` for always-on hybrids. Open outages stay open until the device responds; optional quiet hours without coordinates must be set together. |
| `grabber_stale` | critical | Grabber loop heartbeat stale (same time limit) |
| `zero_production_daylight` | warning | `current_power_produced_kw` ≤ 0.05 kW for 45 minutes in solar daylight with suitable weather as above. With no coordinates, fixed-hour rules require explicit `daylight_rules_enabled`. Recovers only after production exceeds twice the zero threshold for the clear period. |
| `production_below_forecast` | warning | Daily produced-counter delta below `below_forecast_fraction` (default 35%) of hourly forecast progress after local 14:00; expected progress must exceed 2 kWh. Weather guarded and debounced for 30 minutes; recovery fraction is 10 points higher. |
| `production_below_baseline` | warning | Daily produced delta below 45% of median scaled to forecast daylight progress for two consecutive suitable-weather days; requires at least 7 history days. Same weather guard and 30-minute debounce; cloudy days break the streak. Without coordinates, uses elapsed clock-day fraction. |
| `production_spike` | warning | Today’s production &gt; `spike_multiplier` × median (min `spike_min_delta_kwh`) |
| `consumption_spike` | warning | **Off by default**. Optional usage information: daily consumed delta above `consumption_spike_multiplier` × recent median (min `consumption_spike_min_kwh`). |
| `battery_low_soc` | warning | `battery_soc_percent` on device ≤ `battery_low_soc_percent` (only if device exposes SOC) |
| `battery_stuck` | info | SOC unchanged &lt; 0.5% for 120 minutes in daylight, excluding near-full/near-low SOC. On drivers with battery power, requires at least 0.2 kW of measured battery flow; an idle battery during bad weather is normal. Legacy SOC-only readings use the weather guard when available. Recovers after SOC moves. |
| `inverter_dc_without_ac` | warning | **Requires actual DC, AC, and battery power** (Fronius hybrid). At least 0.5 kW DC remains after subtracting battery charging, but AC ≤ 0.05 kW for 5 minutes in daylight. Charging all available DC does not alert; low input cannot prove recovery. |
| `panels_mppt_imbalance` | warning | **Requires per-MPPT powers and configured capacities** (Sunsynk). A comparable input produces &lt;25% of its strongest capacity-normalized peer for 15 daylight minutes, with a peer producing ≥20% of its rating. Recovery requires a ratio ≥40% in strong light. |
| `battery_fault` | critical | **Requires `battery_mode`** (Fronius hybrid). A documented `none operable`, `non operable (voltage)`, `non operable (temperature)`, or `stopped (temperature)` state for 5 minutes. This is the battery's fault state, not the API request's `Head.Status`. No invented numeric temperature/voltage limits. |
| `battery_soc_jump` | warning | **Requires SOC, battery power, and configured usable `battery_capacity_kwh`**. Repeated jumps/drops for 2 minutes exceed a 5-point tolerance plus the energy possible at measured power (25% allowance), or go against a consistent charge/discharge direction. A sampling gap &gt; `max(180 s, 3 × evaluate_interval_s)` resets the sample; no inference is made across missing reads. |
| `battery_charge_stalled` | warning | **Off by default; requires SOC, battery power, PV power, actual export, and normal battery mode**. SOC &lt;95%, PV/export ≥0.5 kW, and absolute battery power ≤0.05 kW for 30 daylight minutes while PV charging is expected. Full, suspended, disabled, calibrating, or no-surplus batteries do not alert. |

Thresholds are under the `alerts:` key in `config.yml` (all optional).

Outbound webhook/SMTP notifications are **not** part of this release; alerts are in-app only.

### API

- `GET /query?type=alerts` — `status=list|open`, `resolved_limit` (≤200), `resolved_cursor` (`ended_at,id` keyset paging; `resolved_offset` is rejected). Polls should refresh open alerts plus the first resolved page only. Invalid parameters return HTTP 400; query failures return `state: error` (not an empty ok).
- `POST /alerts/acknowledge` with `Content-Type: application/json` and body `{"id": <number>}`
- `GET /health` includes `open_alerts` and `forecast_state`

### Dummy fault simulation

```yaml
dummy:
  fault_mode: battery_soc_jump
  battery_soc_percent: 85
alerts:
  panels_mppt_capacity_kw: [4, 4]
  battery_capacity_kwh: 10
  battery_charge_stalled_enabled: true
```

Supported modes: `offline`, `zero_daylight`, `stale`, `battery_stuck`, `inverter_dc_without_ac`, `panels_mppt_imbalance`, `battery_fault`, `battery_soc_jump`, and `battery_charge_stalled`. `off` / `none` / `false` disable faults. Battery fault modes default SOC to 50% when it is not configured. `battery_fault` simulates the documented temperature fault mode, not an unavailable thermometer. `zero_daylight` needs a suitable weather forecast at the Bataan coordinates, or explicit fixed-hour daylight rules without coordinates.

## Database migration

`ensure_feature_schema()` runs on grabber startup and once when the web server starts (if `data/db.sqlite` exists). GET handlers do not migrate. Safe on existing production databases and fresh installs (uses `schema_meta` like other migrations).

The component migration adds a non-null checked column with `system` as the unknown-rule default, backfills existing open/resolved rows, and preserves ids, acknowledgements, details, and rule state. It acquires the SQLite writer lock before checking/altering the schema so concurrent server/grabber startups are safe. A trigger also classifies inserts from an older grabber during an upgrade. Legacy alert GETs infer the component without writing.

## Validation and replays

`pytest/fixtures/bataan_profiles.json` contains explicit **synthetic engineering profiles**, not recorded site measurements: an 8 kW clear dry-season curve, monsoon overcast, near-zero typhoon production, and a partial-day inverter outage. The outage passes DC/AC/battery values through the actual Fronius driver mapper: DC is available but AC drops to 0.02 kW from 08:00–16:00, then recovers. It opens conversion and production-underforecast alerts; the weather profiles open no equipment alerts. A measured Bataan outage log can replace this fixture when one is available.

Minute-by-minute tests use actual opening/clearing durations, exercise each new dummy mode through the grabber snapshot, cover missing/nonfinite/stale data and daylight gates, reject charge scheduling/full-battery/unequal-capacity false positives, and verify baseline streaks across monsoon/typhoon days. API tests compare SQLite bytes before and after GETs on migrated and legacy schemas. UI checks cover EN/DE/FR messages and component labels.

```sh
source .venv/bin/activate
PYTHONPATH=backend python3 -m pytest pytest -q
python3 -m flake8 . --exclude=.git,.venv --max-line-length=127 --count --statistics
```

For a macOS sandbox that denies Chromium Mach-port IPC, set `STRATASOLAR_TEST_SINGLE_PROCESS=1` for the test command. This launches a real Chromium browser in one process; it does not skip or mock browser tests. Keep Playwright's browser cache and `TMPDIR` in the local `.venv` if the environment restricts filesystem writes.

## Known limitations

- **No unsupported diagnostics:** Neither production driver currently reads inverter fault codes, inverter/battery temperatures, or battery voltage. No standalone numeric overtemperature/voltage rules are enabled. Sunsynk battery rules remain silent until its driver actually exposes battery telemetry.
- **Weather inference:** No driver supplies an irradiance sensor. Weather-based underperformance remains an indication to inspect equipment; a materially wrong but fresh forecast cannot establish a definite PV hardware failure. Missing/stale weather is suppressed rather than replaced with a sunny history curve.
- **Battery policy/capacity:** SOC/power checks need the actual usable battery capacity. Charge-stall detection needs an explicitly enabled policy that expects PV charging. Legacy SOC-only stuck detection cannot prove battery power flow.

- **Baseline without lat/lon:** `production_below_baseline` uses a 2-day streak and scales the median by elapsed day fraction; very noisy or partial-day data can still be sensitive compared to weather-gated sites with coordinates.
- **Low-sun lag:** On days when the sun briefly rises above 0°, `device_unreachable` can open shortly after the grace window if the device was offline during that window.
- **Sleeping inverters below +1°:** Devices that only wake when the sun is clearly up may still get brief `device_unreachable` windows on low-sun days when modeled elevation is between 0° and about +1°.
- **Short sun days:** On days with only a few minutes above 0°, outage detection can lag until after the sunrise grace.
- **Polar night:** With no sun above 0°, `device_unreachable` and daylight production rules stay suppressed; a device offline all winter is only surfaced by `grabber_stale` if the grabber loop itself stops updating.
- **Open-Meteo timeout:** `forecast.open_meteo_timeout_s` (default 15, range 3–60) is one wall-clock budget per refresh for both archive and forecast HTTP calls; each call also uses the per-read idle limit above.
- **Docker compose:** A stock `docker-compose` checkout may not ship `config.yml`; copy from `templates/config.yml` before first run.
