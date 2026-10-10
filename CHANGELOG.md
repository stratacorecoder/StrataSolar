# Changelog

## Unreleased

- Preserve the existing 30° tilt when `forecast.panel_tilt_deg` is omitted and restore the 06:00–20:00 history-forecast window. The shipped Bataan template explicitly uses a 15° tilt for new/default Bataan installs.
- Detect zero daytime production even when weather forecasts are missing or dim, make low-SOC notices opt-in, and compare MPPT inputs near solar noon to avoid normal reserve and shading alerts.
- Respect configured and driver-reported battery charge limits, recognize additional Fronius battery modes, and suppress SOC-jump warnings during BMS recalibration.
- Add Sunsynk single-phase battery SOC and signed power reads at registers 184 and 190, preserving negative charging and positive discharging. Battery-mode diagnostics remain unavailable on this driver.
- Align Open-Meteo radiation with the preceding hour, use realistic Bataan storm replays, and repair translated alert component labels and live counts.
