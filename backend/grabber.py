import sys
import time
import logging
import importlib
import signal
from os.path import exists
# Project imports
from aggregates import (
    _ensure_meta_table,
    migrate_legacy_all_time_baseline,
    touch_device_success_heartbeat,
    touch_grabber_loop_heartbeat,
)
from config import Config, ConfigError
from database import Database
from energy_recording import (
    CounterResetCompensator,
    CounterResetSettings,
    counters_should_be_skipped,
)
from local_time import (
    config_time_zone,
    configure_process_time_zone_at_startup,
    local_now,
    local_today,
)
from logging_setup import setup_process_logging
import version


# Real time (24h) data
NUM_REAL_TIME_VALUES = 24*60  # 24h * 60 Minutes
real_time_seconds_counter = 0
config = None
run = True
_counter_compensator = None


def init_counter_compensator(grabber_config=None, clock=None):
    '''Create or replace the process-wide reset compensator (tests).'''
    global _counter_compensator
    settings = CounterResetSettings(grabber_config or {})
    _counter_compensator = CounterResetCompensator(settings, clock=clock)
    return _counter_compensator


def _compensator():
    if _counter_compensator is None:
        grabber_cfg = {}
        if config is not None:
            grabber_cfg = config.config_data.get('grabber') or {}
        init_counter_compensator(grabber_cfg)
        db = Database("data/db.sqlite")
        try:
            _counter_compensator.load_persisted(db)
        finally:
            db.close()
    return _counter_compensator


# Helper function to insert new values into the DB
def insert_historical_values(
        db,
        table_name,
        date_string,
        produced,
        consumed,
        fed_in):
    '''Helper function to insert new values into the DB.'''
    if counters_should_be_skipped(produced, consumed, fed_in):
        return
    query = f"SELECT * FROM {table_name} WHERE date='{date_string}'"
    rows = db.execute(query)

    if len(rows) == 0:
        # Create new row
        query = (f"INSERT INTO {table_name} VALUES ('{date_string}',"
                 f"{str(produced)}, {str(produced)}, "
                 f"{str(consumed)}, {str(consumed)}, "
                 f"{str(fed_in)}, {str(fed_in)})")
        db.execute(query)
    else:
        if (table_name == "all_time"
                and rows[0][1] == 0 and rows[0][2] == 0
                and rows[0][3] == 0 and rows[0][4] == 0
                and rows[0][5] == 0 and rows[0][6] == 0):
            # Baseline device counters so all_time deltas match summed history.
            query = (f"UPDATE {table_name} SET "
                     f"produced_a = {str(produced)}, "
                     f"produced_b = {str(produced)}, "
                     f"consumed_a = {str(consumed)}, "
                     f"consumed_b = {str(consumed)}, "
                     f"fed_in_a = {str(fed_in)}, "
                     f"fed_in_b = {str(fed_in)} "
                     f"WHERE date='{date_string}'")
        else:
            comp = _compensator()
            pa, pb, ca, cb, fa, fb, reset = comp.apply_row(
                table_name, rows[0], produced, consumed, fed_in)
            if reset:
                logging.info(
                    "Grabber: counter reset compensated for %s on %s",
                    table_name, date_string)
            query = (f"UPDATE {table_name} SET "
                     f"produced_a = {str(pa)}, produced_b = {str(pb)}, "
                     f"consumed_a = {str(ca)}, consumed_b = {str(cb)}, "
                     f"fed_in_a = {str(fa)}, fed_in_b = {str(fb)} "
                     f"WHERE date='{date_string}'")
        db.execute(query)


# Helper function to insert current values into the DB
def insert_current_values(
        db,
        produced,
        consumed_grid,
        consumed_pv,
        consumed_total,
        fed_in):
    '''Helper function to insert current values into the DB.'''
    rows = db.execute("SELECT * FROM current WHERE date='cur'")

    if len(rows) == 0:
        # Create day row
        query = (f"INSERT INTO current VALUES ('cur', "
                 f"{str(produced)}, {str(consumed_grid)}, "
                 f"{str(consumed_pv)}, {str(consumed_total)}, "
                 f"{str(fed_in)})")
        db.execute(query)
    else:
        # Update existing row
        query = (f"UPDATE current SET "
                 f"produced = {str(produced)}, "
                 f"consumed_grid = {str(consumed_grid)}, "
                 f"consumed_pv = {str(consumed_pv)}, "
                 f"consumed_total = {str(consumed_total)}, "
                 f"fed_in = {str(fed_in)} "
                 f"WHERE date='cur'")
        db.execute(query)


# Helper function to insert the high score values into the DB
def insert_high_scores(
        db,
        date_str,
        current_production_kw):
    '''Helper function to insert high score values into the DB.'''
    # Make sure table exists
    query = ("CREATE TABLE IF NOT EXISTS highscores "
             "(type STRING PRIMARY KEY, date STRING, value REAL)")
    db.execute(query)
    # Get current value
    query = "SELECT * FROM highscores WHERE type IS 'production'"
    rows = db.execute(query)
    if not rows:
        cur_high_score_value = 0.0
        query = ("INSERT INTO highscores (type,date,value) "
                 "VALUES('production','...',0.0);")
        db.execute(query)
    else:
        cur_high_score_value = rows[0][2]
    # Check if we have a high score
    if current_production_kw > cur_high_score_value:
        query = (f"UPDATE highscores SET "
                 f"value = {str(current_production_kw)}, "
                 f"date = '{date_str}' WHERE type IS 'production'")
        db.execute(query)


# Helper function to insert new values into the DB
def insert_real_time_values(db, time_string2, produced, consumed, fed_in):
    '''Helper function to insert new values into the DB.'''
    # Insert new data
    query = (f"INSERT INTO real_time (time, produced, consumed, fed_in) "
             f"VALUES('{time_string2}', {produced}, {consumed}, {fed_in})")
    db.execute(query)
    # Limit data
    query = (f"DELETE FROM real_time WHERE ID IN ("
             f"SELECT ID FROM real_time "
             f"ORDER BY ID DESC "
             f"LIMIT -1 OFFSET {NUM_REAL_TIME_VALUES})")
    db.execute(query)


# Helper function to insert high res values into the DB
def insert_high_res_values(
        db,
        day_string,
        time_string,
        produced,
        consumed,
        fed_in):
    '''Helper function to insert high res values into the DB.'''
    # Make sure table exists
    query = ("create table if not exists high_res "
             "(date STRING PRIMARY KEY, hrvalues STRING)")
    db.execute(query)

    # Get current entry
    query = (f"SELECT * FROM high_res WHERE date='{day_string}'")
    rows = db.execute(query)
    old_values = ""
    if not rows:
        # Create new row
        query = (f"INSERT INTO high_res (date,hrvalues) "
                 f"VALUES ('{day_string}', '');")
        db.execute(query)
    else:
        old_values = rows[0][1]

    # Append new values to old values
    new_value = (f"[\"{time_string}\","
                 f"{str(round(produced, 3))},"
                 f"{str(round(consumed, 3))},"
                 f"{str(round(fed_in, 3))}],")
    old_values += new_value

    # Update DB
    query = (f"UPDATE high_res SET "
             f"hrvalues = '{old_values}' "
             f"WHERE date='{day_string}'")
    db.execute(query)


# Helper function to create a new DB
def create_new_db():
    '''Helper function to create a new DB.'''
    new_db = Database("data/db.sqlite")

    # Historical data tables
    table_names = ["days", "months", "years", "all_time"]
    for name in table_names:
        query = (f"create table if not exists {name} ("
                 "date STRING PRIMARY KEY,"
                 "produced_a REAL, produced_b REAL,"
                 "consumed_a REAL, consumed_b REAL,"
                 "fed_in_a REAL, fed_in_b REAL)")
        new_db.execute(query)

    # Add initial all time row
    query = ("INSERT INTO all_time VALUES ('all_time',0,0,0,0,0,0)")
    new_db.execute(query)

    # Current data table
    query = ("create table if not exists current"
             "(date STRING PRIMARY KEY, "
             "produced REAL, consumed_grid REAL, consumed_pv REAL, "
             "consumed_total REAL, fed_in REAL)")
    new_db.execute(query)

    # Real time data table
    query = ("create table if not exists real_time"
             "(ID INTEGER PRIMARY KEY AUTOINCREMENT, "
             "time STRING, produced REAL, consumed REAL, fed_in REAL)")
    new_db.execute(query)
    # Insert null data
    for x in range(NUM_REAL_TIME_VALUES):  # 24h * 60 minutes
        query = (f"INSERT INTO real_time VALUES"
                 f"('{str(x)}', '...', '0.0', '0.0', '0.0')")
        new_db.execute(query)

    # Add highscores
    query = ("CREATE TABLE IF NOT EXISTS highscores "
             "(type STRING PRIMARY KEY, date STRING, value REAL)")
    new_db.execute(query)
    query = ("INSERT INTO highscores (type,date,value) "
             "VALUES('production','...',0.0);")
    new_db.execute(query)

    # Add high res data table
    query = ("CREATE TABLE IF NOT EXISTS high_res "
             "(date STRING PRIMARY KEY, hrvalues STRING)")
    new_db.execute(query)

    _ensure_meta_table(new_db)


# Loads the device class with the given name
def load_device_plugin(device_name):
    '''Loads the device class with the given name.'''
    try:
        module = importlib.import_module("devices." + device_name)
    except ModuleNotFoundError as exc:
        raise ConfigError(
            f"unknown device type '{device_name}'") from exc
    try:
        class_ = getattr(module, device_name)
    except AttributeError as exc:
        raise ConfigError(
            f"device plugin '{device_name}' is missing class "
            f"'{device_name}'") from exc
    return class_(config)


# Sets the time zone environment variable
def set_time_zone(tz):
    '''Sets the time zone environment variable.'''
    if not tz:
        logging.warning("Grabber: Warning: No time zone set")
        return
    logging.info("Grabber: Setting time zone to %s", tz)
    configure_process_time_zone_at_startup(tz)
    logging.info("Grabber: Time is now %s", time.strftime('%X %x %Z'))


# Updates data in the data base
def update_data(device):
    '''Updates data in the data base.'''
    global real_time_seconds_counter

    # Download new data from the actual PV device
    device.update()

    # Open connection to data base
    db = Database("data/db.sqlite")

    tz = config_time_zone(config)
    today = local_today(tz)
    year_string = today.strftime("%Y")
    month_string = today.strftime("%Y-%m")
    day_string = today.strftime("%Y-%m-%d")

    comp = _compensator()
    comp.begin_poll()

    insert_historical_values(
        db,
        "days",
        day_string,
        device.total_energy_produced_kwh,
        device.total_energy_consumed_kwh,
        device.total_energy_fed_in_kwh)

    insert_historical_values(
        db,
        "months", month_string,
        device.total_energy_produced_kwh,
        device.total_energy_consumed_kwh,
        device.total_energy_fed_in_kwh)

    insert_historical_values(
        db,
        "years",
        year_string,
        device.total_energy_produced_kwh,
        device.total_energy_consumed_kwh,
        device.total_energy_fed_in_kwh)

    insert_historical_values(
        db,
        "all_time",
        "all_time",
        device.total_energy_produced_kwh,
        device.total_energy_consumed_kwh,
        device.total_energy_fed_in_kwh)

    comp.finish_poll()
    comp.save_persisted(db)

    insert_current_values(
        db,
        device.current_power_produced_kw,
        device.current_power_consumed_from_grid_kw,
        device.current_power_consumed_from_pv_kw,
        device.current_power_consumed_total_kw,
        device.current_power_fed_in_kw)

    insert_high_scores(db, day_string, device.current_power_produced_kw)

    real_time_seconds_counter = real_time_seconds_counter - \
        config.config_data['grabber']['interval_s']
    if real_time_seconds_counter <= 0:
        time_string = local_now(tz).strftime("%H:%M")
        if logging.getLogger().level == logging.DEBUG:
            logging.debug((f"Grabber: capturing real time data({time_string}:"
                           f"{device.current_power_produced_kw}, "
                           f"{device.current_power_consumed_total_kw}, "
                           f"{device.current_power_fed_in_kw})"))

        insert_real_time_values(
            db,
            time_string,
            device.current_power_produced_kw,
            device.current_power_consumed_total_kw,
            device.current_power_fed_in_kw)

        insert_high_res_values(
            db,
            day_string,
            time_string,
            device.current_power_produced_kw,
            device.current_power_consumed_total_kw,
            device.current_power_fed_in_kw)

        real_time_seconds_counter = 60  # Reset counter to one minute

    touch_device_success_heartbeat(db)


def _load_device_or_wait(device, interval_s):
    '''Load the device plugin once; retry only I/O failures.'''
    if device is not None:
        return device
    device_name = config.config_data['device']['type']
    logging.info("Grabber: Loading device adapter '%s'", device_name)
    try:
        return load_device_plugin(device_name)
    except ConfigError as exc:
        logging.error("Grabber: %s", exc)
        sys.exit(1)
    except Exception:
        logging.exception(
            "Grabber: device adapter unavailable; retrying")
        time.sleep(interval_s)
        return None


def _grabber_loop_iteration(device, interval_s):
    '''One grabber poll: heartbeat, device update, sleep is outside.'''
    try:
        loop_db = Database("data/db.sqlite")
        touch_grabber_loop_heartbeat(loop_db)
        loop_db.close()
    except Exception:
        logging.exception("Grabber: loop heartbeat update failed")

    device = _load_device_or_wait(device, interval_s)
    if device is None:
        return None

    if logging.getLogger().level == logging.DEBUG:
        time_string = local_now(
            config.config_data.get("time_zone")).strftime("%H:%M")
        logging.debug(f"Grabber: {time_string}: Updating device data")

    try:
        update_data(device)
    except Exception:
        logging.exception("Updating data from device failed")
    return device


# This is called when SIGTERM is received
def handler_stop_signals(signum, frame):
    global run
    logging.debug("Grabber: SIGTERM/SIGINT received")
    run = False


# Main loop
def main():
    '''Main loop.'''
    global config

    signal.signal(signal.SIGINT, handler_stop_signals)
    signal.signal(signal.SIGTERM, handler_stop_signals)

    setup_process_logging('data/grabber.log')

    logging.info(
        "Starting StrataSolar grabber version %s", version.get_version())

    try:
        logging.info("Grabber: Reading backend configuration from config.yml")
        config = Config("data/config.yml")
    except ConfigError as exc:
        logging.error("Grabber: %s", exc)
        sys.exit(1)

    logging.getLogger().setLevel(config.log_level)
    set_time_zone(config_time_zone(config))

    logging.info("Grabber: Checking if data base exists")
    if not exists("data/db.sqlite"):
        logging.info("Grabber: Data base does not exist. Creating new one")
        create_new_db()
    else:
        migrate_legacy_all_time_baseline(Database("data/db.sqlite"))

    try:
        init_counter_compensator(config.config_data.get('grabber'))
    except ConfigError as exc:
        logging.error("Grabber: %s", exc)
        sys.exit(1)
    persist_db = Database("data/db.sqlite")
    _compensator().load_persisted(persist_db)
    persist_db.close()

    logging.debug("Grabber: Entering main loop")
    device = None
    interval_s = config.config_data['grabber']['interval_s']
    while run:
        device = _grabber_loop_iteration(device, interval_s)
        time.sleep(interval_s)

    logging.info("Grabber: Exiting main loop")
    logging.info("Grabber: Shutting down gracefully")


if __name__ == "__main__":
    main()
