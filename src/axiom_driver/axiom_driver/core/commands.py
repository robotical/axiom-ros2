"""Validate and encode descriptor commands using the firmware cmdraw contract."""

import math
import re
import struct


def command_format(action):
    if action.get('vt'):
        raise ValueError('This command needs a custom value format')
    fmt = action.get('t', '')
    if not isinstance(fmt, str) or not re.fullmatch(r'[<>!]?([0-9]*[bBhHiIlLqQfd?])*', fmt):
        raise ValueError('Unsupported numeric command format')
    return fmt if fmt.startswith(('<', '>', '!')) else '<' + fmt


def encode_command(action, values):
    """Return writes and bounded pauses; never truncate or wrap user arguments."""
    fmt = command_format(action)
    fields = re.findall(r'([0-9]*)([bBhHiIlLqQfd?])', fmt[1:])
    if sum(int(count or 1) for count, _ in fields) > 1024:
        raise ValueError('Descriptor command exceeds 1024 arguments')
    kinds = [kind for count, kind in fields for _ in range(int(count or 1))]
    if len(values) != len(kinds):
        raise ValueError(f'Expected {len(kinds)} numeric arguments')
    converted = []
    for index, (value, kind) in enumerate(zip(values, kinds)):
        if (isinstance(value, bool) or not isinstance(value, (int, float))
                or not math.isfinite(value)):
            raise ValueError('Arguments must be finite numbers')
        limits = action.get('r')
        if limits and not float(limits[0]) <= value <= float(limits[1]):
            raise ValueError(f'Argument {index} must be between {limits[0]} and {limits[1]}')
        if action.get('f') == 'LEDPIX' and index == 0:
            if not 0 <= value < int(action.get('NX', 1)) * int(action.get('NY', 1)):
                raise ValueError('Pixel index is outside the descriptor grid')
        if len(values) == 1:
            value = (value - action.get('sub', 0)) * action.get('mul', 1)
        if kind not in 'fd':
            if not math.isclose(value, round(value), abs_tol=1e-9):
                raise ValueError('This argument must encode as an integer')
            value = int(round(value))
            if kind == '?' and value not in (0, 1):
                raise ValueError('Boolean argument must be 0 or 1')
        converted.append(value)
    try:
        data = struct.pack(fmt, *converted).hex()
    except (struct.error, OverflowError) as exc:
        raise ValueError(f'Argument does not fit the descriptor format: {exc}') from exc
    text = action.get('w', '') + data + action.get('wz', '')
    operations = []
    for part in text.split('&'):
        if re.fullmatch(r'p[0-9]+', part):
            pause = int(part[1:])
            if pause > 1000:
                raise ValueError('Descriptor pause exceeds 1000 ms')
            operations.append(pause / 1000)
        elif part and re.fullmatch(r'([0-9a-fA-F]{2})+', part):
            operations.append(part.lower())
        else:
            raise ValueError('Descriptor command has an invalid write sequence')
    return operations
