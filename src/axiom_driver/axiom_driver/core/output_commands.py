"""Typed output-topic contracts derived from supported device descriptors."""

import math
import re

from .commands import command_format, encode_command


def output_topics(metadata, action):
    """Describe angle and RGB topic inputs; unrelated operations remain services."""
    command_format(action)
    name = action['n'].strip().lower().replace('_', ' ')
    if name in ('angle', 'set angle') and (
            'SRVO' in metadata.get('clas', [])
            or any(item.get('n') == 'enable' for item in metadata.get('actions', []))):
        if not re.fullmatch(r'[<>!]?[bBhHiIlLqQfd]', action.get('t', '')):
            raise ValueError('Servo angle requires one numeric argument')
        scale, offset = float(action.get('mul', 1)), float(action.get('sub', 0))
        if not math.isfinite(scale) or not scale or not math.isfinite(offset):
            raise ValueError('Invalid servo angle scaling')
        attributes = (metadata.get('resp') or {}).get('a', [])
        unit = action.get('u') or next((item.get('u') for item in attributes
                                       if item.get('n') == 'angle'), None) or 'degrees'
        if unit not in ('degrees', 'deg', 'radians', 'rad'):
            raise ValueError('Unsupported servo angle unit')
        return [{'kind': 'angle', 'unit': 'rad', 'command_unit': unit}]
    if action.get('f') == 'LEDPIX':
        count = int(action.get('NX', 1)) * int(action.get('NY', 1))
        if not 1 <= count <= 1024:
            raise ValueError('LED grid must contain 1..1024 pixels')
        # Check the indexed RGB contract before creating any subscriptions.
        encode_command(action, [count - 1, 0, 0, 0])
        return [{'kind': 'colour', 'unit': 'normalized_rgb', 'pixel': index}
                for index in range(count)]
    if name in ('color', 'colour', 'rgb'):
        if action.get('t') == '>I' and action.get('f') == '06x':
            encode_command(action, [0])
            return [{'kind': 'colour', 'unit': 'normalized_rgb', 'packed_rgb': True}]
        if not re.fullmatch(r'[<>!]?(BBB|3B)', action.get('t', '')):
            raise ValueError('RGB colour requires three byte arguments')
        encode_command(action, [0, 0, 0])
        return [{'kind': 'colour', 'unit': 'normalized_rgb'}]
    return []


def output_values(action, spec, value):
    """Convert ROS radians or normalized RGB to validated descriptor arguments."""
    if spec['kind'] == 'angle':
        if not math.isfinite(value):
            raise ValueError('Angle must be finite')
        angle = math.degrees(value) if spec['command_unit'] in ('degrees', 'deg') else value
        limits = action.get('r')
        if limits and not float(limits[0]) <= angle <= float(limits[1]):
            raise ValueError('Angle is outside the descriptor limits')
        if action['t'][-1] not in 'fd':
            scale, offset = float(action.get('mul', 1)), float(action.get('sub', 0))
            if not math.isfinite(scale) or not scale or not math.isfinite(offset):
                raise ValueError('Invalid servo angle scaling')
            angle = round((angle - offset) * scale) / scale + offset
        values = [angle]
    else:
        if not all(math.isfinite(channel) and 0 <= channel <= 1 for channel in value):
            raise ValueError('RGB channels must be finite values in 0..1')
        values = [round(channel * 255) for channel in value]
        if 'pixel' in spec:
            values.insert(0, spec['pixel'])
        elif spec.get('packed_rgb'):
            values = [(values[0] << 16) | (values[1] << 8) | values[2]]
    encode_command(action, values)
    return values
