'''Convert panel azimuth between compass and Open-Meteo conventions.'''

from config import ConfigError


def compass_azimuth_to_open_meteo(compass_deg):
    '''
    Compass: 0=north, 90=east, 180=south, 270=west.
    Open-Meteo: 0=south, -90=east, 90=west, ±180=north.
    '''
    om = float(compass_deg) - 180.0
    while om > 180.0:
        om -= 360.0
    while om < -180.0:
        om += 360.0
    return om


def validate_open_meteo_azimuth(om_deg):
    if om_deg < -180.0 or om_deg > 180.0:
        raise ConfigError(
            'forecast.panel_azimuth_deg out of range after conversion; '
            'use compass degrees 0–360 (180=south)')
