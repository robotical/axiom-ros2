"""Engineering values and ROS units; a unit label alone is not a quantity."""

import math


def to_si(value, unit, *, attribute='', device_type=''):
    """Return (value, unit) or (None, None) when the quantity is ambiguous."""
    name = attribute.lower()
    unit = (unit or '').strip()
    scale, offset, output = 1.0, 0.0, unit
    if unit == 'g':
        if name in ('ax', 'ay', 'az') or 'accel' in name:
            scale, output = 9.80665, 'm/s^2'
        elif 'weight' in name or 'mass' in name or device_type == 'M5-Weight':
            scale, output = 0.001, 'kg'
        else:
            return None, None
    elif unit in ('&deg;/s', 'deg/s', '°/s', 'degrees/s'):
        scale, output = math.pi / 180.0, 'rad/s'
    elif unit in ('&deg;', 'deg', '°', 'degrees'):
        scale, output = math.pi / 180.0, 'rad'
    elif unit in ('mm', 'cm', 'mV', 'mA'):
        scale, output = {
            'mm': (0.001, 'm'),
            'cm': (0.01, 'm'),
            'mV': (0.001, 'V'),
            'mA': (0.001, 'A'),
        }[unit]
    elif unit in ('%', '%RH'):
        scale, output = 0.01, 'fraction'
    elif unit in ('°C', '&deg;C', 'degC'):
        output = 'degC'  # ROS Temperature uses Celsius (REP-103).
    elif unit not in (
        'm',
        'kg',
        's',
        'Hz',
        'V',
        'A',
        'rad',
        'rad/s',
        'm/s^2',
        'Pa',
        'W',
        'T',
        'lux',
        'degC',
    ):
        return None, None

    def convert(v):
        return float(v) * scale + offset

    try:
        return ([convert(v) for v in value] if isinstance(value, list) else convert(value)), output
    except (TypeError, ValueError, OverflowError):
        return None, None
