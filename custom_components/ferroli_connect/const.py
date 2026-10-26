"""Constants and validation shared by the climate entity and transport."""
import math

DOMAIN = 'ferroli_connect'
NAME = 'Ferroli Connect'
STALE_SECONDS = 600


def valid_temperature_limits(low, high):
    """A pair of zero placeholders must never become a writable range."""
    return (type(low) in (int, float) and type(high) in (int, float)
            and math.isfinite(low) and math.isfinite(high) and low < high)
