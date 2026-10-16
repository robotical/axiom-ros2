"""Standard scalar outputs from already decoded descriptor attributes."""

import math
import re


def scalar_output(name, entry):
    """
    Return (kind, value, published unit), or None for unsupported values.

    Boolean/text contracts follow the descriptor even when validation replaced
    a reading with NaN. Numeric values are engineering values, never raw counts.
    """
    value = entry['value']
    if isinstance(value, (list, tuple, dict)):
        return None
    attr = entry['meta']
    wire_type = attr.get('t', '').lstrip('@=<>!')
    valid = entry['valid']
    if attr.get('o') == 'bool' or wire_type == '?':
        return ('bool', bool(value), None) if valid and isinstance(value, (bool, int)) else None
    if (re.fullmatch(r'(\d*[scp]|[sp]\[\d+\])', wire_type)
            or attr.get('o') in ('str', 'string')):
        return ('string', value, None) if valid and isinstance(value, str) else None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    si_value = entry['si_value']
    unit = entry['si_unit'] if si_value is not None else entry['unit']
    number = float(si_value if si_value is not None else value)
    if not valid or not math.isfinite(number):
        number = math.nan
    # A lux label alone does not make an infrared/raw channel photometric light.
    if name.lower() in ('ambient', 'als', 'white', 'visible', 'illuminance', 'light') and (
        entry['si_unit'] == 'lux'
    ):
        return 'illuminance', number if number >= 0 else math.nan, 'lux'
    return 'float', number, unit or None
