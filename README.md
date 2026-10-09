# :sunny: StrataSolar

![Python checks](https://github.com/stratacorecoder/StrataSolar/actions/workflows/python_lint.yml/badge.svg)
![Unit tests](https://github.com/stratacorecoder/StrataSolar/actions/workflows/unit_tests.yml/badge.svg)
![Docker build](https://github.com/stratacorecoder/StrataSolar/actions/workflows/docker.yml/badge.svg)

StrataSolar is a free, open source and vendor independent solar monitoring system. It collects relevant data from your inverter/smart meter and stores them safely in a data base.

A modern and beautiful web frontend allows you to visualize the data on any device. The user interface is highly responsive and works great on any screen size, from a small smart phone to a huge PC monitor.

StrataSolar can easily be self hosted on a Raspberry Pi or a NAS by using Docker. It works 100% offline, no cloud is involved. All your data stays under your control.

StrataSolar is a fork of the open-source [Sunalyzer](https://github.com/borisbrock/Sunalyzer) project by Boris Brock.

<a href="https://www.buymeacoffee.com/borisbrock" target="_blank"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-yellow.png" alt="Buy Me A Coffee" style="height: 60px !important;width: 217px !important;" ></a>

![Screenshot](doc/screenshot.png)

## Main Features

- 100% free and open source.
- Easy to set up and configure (e.g. on a Raspberry Pi or a NAS).
- Fully local storage of collected data. No cloud or 3rd party involved.
- Hardware vendor independent.
- Beautiful and highly dynamic user interface. Desktop and mobile friendly.
- Visualization of all important values via graphs.
- Detailed information and statistics with lots of useful information.
- High resolution historical data (1 minute resolution) is kept.
- Very compact database: roughly 15mb of storage are required per year.
- CSV download (manually or via API) of all relevant data.

## Supported Languages

Currently StrataSolar provides an **English** and a **German** user interface. The language can be changed on the fly via the user interface.

## Supported Devices

StrataSolar provides integrations for the following device types (inverters/smart meters):
* Fronius (Symo/Gen24)
* Sunsynk/Deye (single-phase hybrid inverters, via WiFi/LAN dongle or RS485)
* Dummy device (for testing purposes)

Contributions for the support of additional devices are welcome. Please feel free to reach out to me or submit a pull request directly.


## Installation instructions

StrataSolar comes as a self contained and easy to set up Docker container. Thus it can be run on various different platforms. Detailed installation instructions for the Raspberry Pi and Synology DiskStation NAS systems are provided below.

### General Instructions

1. Create a folder called *data* on your host system. This will contain the configuration file and the data base.
2. Create a configuration YAML file in this data folder. Use [this template](templates/config.yml) as a starting point. A detailed description of the configuration elements can be found below.
3. Build the Docker image from this repository (`docker build -t stratasolar .`), or pull `stratacorecoder/stratasolar:latest` from Docker Hub once that image has been published.
4. Create a container based on the image.
  * The container exposes port 5000. Map this to a port on your host system.
  * The container exposes a volume called *data*. Map this to the *data* folder on your host system created in step 1.
5. Make sure your data folder is regularly backed up as it contains the data base!
6. Start the container. Done!

### Using Docker Compose

If you are using Docker Compose, either run the template from the clone root (`docker compose -f templates/docker-compose.yml up -d --build`) or create a *docker-compose.yml* at the **repository root** like this (do not copy the template verbatim to the root — it uses `build.context: ..` for `-f templates/...`):

```yaml
name: stratasolar

services:
  stratasolar:
    container_name: stratasolar
    build: .
    image: stratasolar:local
    # image: stratacorecoder/stratasolar:latest  # use after publish on Docker Hub
    restart: always
    ports:
      - "8020:5000"
    volumes:
      - /volume1/docker/stratasolar:/data
```

## Deploying

StrataSolar ships as a single Docker image that runs **two processes** under supervisord: the **grabber** (polls your inverter and writes SQLite data under `/data`) and the **web server** (port **5000** inside the container). Map that port on the host (for example `8020:5000` in the compose template).

### Data volume

Mount a host directory on **`/data`**. It must contain:

| File / path | Purpose |
| ----------- | ------- |
| `config.yml` | Instance configuration (see [templates/config.yml](templates/config.yml)) |
| `db.sqlite` | Created automatically by the grabber on first run |
| `*.log` | Optional; grabber and server recreate log files on start |

Back up this folder regularly.

### Environment

| Variable | Default | Notes |
| -------- | ------- | ----- |
| `TZ` | unset in image | **Do not rely on the container OS zone.** Set `time_zone` in `config.yml` (IANA names such as `Asia/Manila` are recommended). Invalid values fall back to **UTC** at startup in both grabber and server. POSIX offset signs are inverted (`GMT+8` means UTC−8). |
| `PYTHONUNBUFFERED` | `1` in image | Logs appear promptly on `docker logs`. |

The image runs as **root** so typical NAS bind mounts keep working without `chown`; files created under `/data` will be owned by root on the host. For stricter setups, create the data directory with ownership matching your policy (or map a `user:` in compose) before mounting.

### Health check

* **HTTP:** `GET /health` → `{"state":"ok"}` when the database is readable and the grabber loop heartbeat is fresh. Staleness uses `max(3 × grabber.interval_s, grabber.interval_s + 60)` seconds since the last loop heartbeat (with the default `interval_s: 5`, that is **65 s**). Returns **503** with `state: degraded` if the DB is unreadable or the heartbeat is older than that limit (for example after the grabber process stops).
* **Logs:** grabber and server write to rotating files under `data/*.log` **and** to stdout/stderr (`docker logs stratasolar` shows both processes).

### Quick start

```bash
mkdir -p /path/to/stratasolar-data
cp templates/config.yml /path/to/stratasolar-data/config.yml
# edit config.yml (device, time_zone, prices, …)
docker build -t stratasolar:local .
docker run -d --name stratasolar \
  -p 8020:5000 \
  -v /path/to/stratasolar-data:/data \
  --restart unless-stopped \
  stratasolar:local
curl -fsS http://localhost:8020/health
curl -fsS 'http://localhost:8020/query?type=current'
```

Or from a clone root: `docker compose -f templates/docker-compose.yml up -d --build`

### Configuration errors

If `config.yml` is missing, empty, or invalid, the failing process logs a clear error (including `missing required key '…'` when a YAML key is absent) and exits with code **1**. supervisord may still shut down with container exit code **0**; with **`restart: unless-stopped`**, Docker restarts the container about every **10 seconds** until the config is fixed—check **`docker logs stratasolar`** (and `data/grabber.log` / `data/server.log` on the volume) for the message. Fix `config.yml` before relying on a long-running deployment. The grabber **retries** unreachable inverters in-process (it does not exit when the device is asleep). Unknown `device.type` values and other configuration errors fail fast at startup (the container will not stay “healthy” while logging import errors forever).

### Cumulative counters and inverter swaps

The grabber stores each poll’s cumulative kWh readings as-is (same as classic Sunalyzer behavior). Samples where **produced, consumed, and fed_in are all zero** are skipped. If an inverter is replaced or a lifetime counter resets, **affected periods may show 0 kWh** until the new counter catches up; the UI clamps displayed totals so values are **never negative**. **Automatic compensation for counter resets is not implemented yet** and will ship in a follow-up change.

### Upgrading and the All Time baseline migration

Versions after the timezone/totals fix may run a **one-time grabber migration** on startup that adjusts only the `all_time` row `_a` columns so stored inverter counters align with summed year history (`schema_meta.all_time_baseline_v1`). It is idempotent and does not change API totals (dashboard uses `SUM(years)`). Upgrading from Sunalyzer: keep your existing `/data` mount; see [Configuration](#configuration) for the `stratasolar:` config rename.

### Docker Hub publish (maintainers)

Release workflow [`.github/workflows/publish.yml`](.github/workflows/publish.yml) pushes to Docker Hub only when repository secrets `DOCKER_HUB_USER_NAME` and `DOCKER_HUB_PASSWORD` are set; otherwise the job is skipped. Image name: `stratacorecoder/stratasolar`.

### Detailed Installation Guide: Synology NAS

If you want to run StrataSolar on a Synology NAS, [click here](doc/install_synology.md) for detailed installation instructions.

### Detailed Installation Guide: Raspberry Pi

If you want to run StrataSolar on a Raspberry Pi, [click here](doc/install_raspberrypi.md) for detailed installation instructions.

## Configuration

> **Upgrading from Sunalyzer:** rename the `sunalyzer:` block in `config.yml` to `stratasolar:` (the server still accepts the old key with a deprecation warning). When updating Docker Compose, keep your **existing host data path** (for example `/volume1/docker/sunalyzer:/data`) so the container still sees your database, or move the folder first (`mv /volume1/docker/sunalyzer /volume1/docker/stratasolar`). Service and container names can be updated as in the template below.

StrataSolar is configured via a YAML file called *config.yml*. This file has to be placed in the data folder before the container is started. An example configuration file can be found [here](templates/config.yml).

### Configuration Settings Overview

| Setting                       | Description                                                                                         |
| ----------------------------- | --------------------------------------------------------------------------------------------------- |
| logging                       | Can be 'normal' (only basic logging) or 'verbose' (verbose logging for debug purposes).             |
| time_zone                     | Time zone for logged timestamps. Prefer IANA names (e.g. `Asia/Manila`, `Europe/Berlin`). POSIX TZ strings are supported; POSIX offset signs are inverted vs UTC (`GMT+8` means UTC−8). Leading/trailing spaces are trimmed. |
| device:type                   | Name of the device plugin to use. Currently "Fronius", "Sunsynk" and "Dummy" are supported.         |
| device:start_date             | The date on which the inverter first started production (YYYY-MM-DD).                               |
| prices:price_per_grid_kwh     | Price for 1 kWh consumed from the grid (e.g. in €).                                                 |
| prices:revenue_per_fed_in_kwh | Revenue for 1 fed in kWh (e.g. in €).                                                               |
| server:ip                     | IP address of the web server. Should be set to 0.0.0.0.                                             |
| server:port                   | Port of the web server. Should be set to 5000.                                                      |
| grabber:interval_s            | Interval in seconds that the grabber will use to query the inverter/smart meter. Default is 5s.     |
| stratasolar:name              | Display name of this StrataSolar instance (shown in the web UI).                                    |

Additional settings are required depending on the selected device plugin:

#### Fronius

| Setting                       | Description                                                   |
| ----------------------------- | ------------------------------------------------------------- |
| fronius::host_name            | IP address or host name of your fronius inverter.             |
| fronius::has_meter            | True/False - Is there a Fronius smart meter present?          |

#### Sunsynk

Sunsynk/Deye single-phase hybrid inverters are read locally (no cloud) over Modbus. Two transports are supported, selected via `sunsynk::connection`:

* `solarman` – talks to the inverter's WiFi/LAN data logger (the "dongle") over TCP using the Solarman V5 protocol. This is the default and needs no extra hardware.
* `modbus_rtu` – talks directly to the inverter's RS485 port via a USB-RS485 adapter. The host serial device must be passed into the container (see below).

| Setting                       | Description                                                                                  |
| ----------------------------- | -------------------------------------------------------------------------------------------- |
| sunsynk::connection           | Transport to use: "solarman" (WiFi/LAN dongle) or "modbus_rtu" (RS485). Default "solarman".   |
| sunsynk::mb_slave_id          | Modbus slave/unit id of the inverter. Default 1.                                             |
| sunsynk::host_name            | (solarman) IP address or host name of the WiFi/LAN data logger.                              |
| sunsynk::logger_serial        | (solarman) Serial number of the data logger (printed on the dongle).                         |
| sunsynk::port                 | (solarman) Solarman V5 TCP port. Default 8899.                                               |
| sunsynk::serial_port          | (modbus_rtu) Host serial device, e.g. /dev/ttyUSB0 (prefer /dev/serial/by-id/...).           |
| sunsynk::baudrate             | (modbus_rtu) Serial baud rate. Sunsynk default 9600.                                         |
| sunsynk::parity               | (modbus_rtu) Serial parity: N, E or O. Default N.                                            |
| sunsynk::stopbits             | (modbus_rtu) Serial stop bits. Default 1.                                                    |
| sunsynk::bytesize             | (modbus_rtu) Serial byte size. Default 8.                                                    |

> **Note on registers:** Sunsynk/Deye Modbus register addresses and scales vary by model and firmware. StrataSolar ships with the de-facto-standard single-phase-hybrid map, but you should verify the values against your own inverter (run with `logging: verbose` to see every decoded value). The register map and references are documented at the top of [backend/devices/Sunsynk.py](backend/devices/Sunsynk.py).

> **RS485 (modbus_rtu) and Docker:** pass the host serial device into the container (`devices: ["/dev/ttyUSB0:/dev/ttyUSB0"]`) and grant access to it (`group_add: ["dialout"]`). See the commented RS485 section in [templates/docker-compose.yml](templates/docker-compose.yml).

## Development Environment

StrataSolar is currently being developed using the following tools and libraries:
* **Operating system**: Arch Linux
* **Development Environment**: Visual Studio Code
* **Programming languages**: Python 3.12, JavaScript, HTML
* **Database**: SQlite
* **Frameworks**: Bootstrap, Chart.js, hammer.js, Fontawesome
* **DevOps**: flake8, pytest, htmlhint, ESlint
* **Deployment**: Docker
