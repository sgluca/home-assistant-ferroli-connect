"""Constants and validation shared by the climate entity and transport."""
import math

DOMAIN = 'ferroli_connect'
NAME = 'Ferroli Connect'
STALE_SECONDS = 600


def valid_temperature_limits(low, high):
    """A pair of zero placeholders must never become a writable range."""
    return (type(low) in (int, float) and type(high) in (int, float)
            and math.isfinite(low) and math.isfinite(high) and low < high)


def temperature_limits(low, high):
    """Use reported bounds, or the official app's 5–35 °C for a zero pair.

    ThermostatActivity sets these constants for manual and automatic setpoints.
    Other malformed pairs are rejected rather than silently discarded.
    """
    if valid_temperature_limits(low, high):
        return low, high
    if type(low) in (int, float) and type(high) in (int, float) and low == high == 0:
        return 5.0, 35.0
    return None
