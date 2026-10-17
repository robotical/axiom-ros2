"""Optional, versioned ROS scalar declarations carried in device metadata."""

import math

from .scalars import scalar_kind, scalar_output


# Public message name -> output kind, native scalar kind, required normalised unit.
MESSAGE_TYPES = {
    'sensor_msgs/msg/Illuminance': ('illuminance', 'float', 'lux'),
    'sensor_msgs/msg/Temperature': ('temperature', 'float', 'degC'),
    'sensor_msgs/msg/RelativeHumidity': ('humidity', 'float', 'fraction'),
    'std_msgs/msg/Float64': ('float', 'float', None),
    'std_msgs/msg/Bool': ('bool', 'bool', None),
    'std_msgs/msg/String': ('string', 'string', None),
}


def parse_ros_mappings(metadata):
    """Return supported declarations and advice; malformed entries do not block peers."""
    if 'ros' not in metadata:
        return {}, []
    block = metadata['ros']
    if (not isinstance(block, dict) or set(block) != {'version', 'attributes'}
            or type(block.get('version')) is not int or block['version'] != 1
            or not isinstance(block.get('attributes'), dict)):
        return {}, ['ros must contain version: 1 and an attributes object']
    response = metadata.get('resp') or {}
    names = {attr['n'] for attr in response.get('a', [])}
    mappings, warnings = {}, []
    for name, declaration in block['attributes'].items():
        if name not in names:
            warnings.append(f'ros.attributes.{name}: attribute is not in resp.a')
        elif (not isinstance(declaration, dict) or set(declaration) != {'message_type'}
              or not isinstance(declaration.get('message_type'), str)
              or declaration['message_type'] not in MESSAGE_TYPES):
            warnings.append(f'ros.attributes.{name}: expected a supported message_type')
        else:
            mappings[name] = declaration['message_type']
    return mappings, warnings


def mapped_scalar_output(message_type, entry):
    """Resolve a declaration using decoded values; incompatible data keeps its fallback."""
    kind, native_kind, required_unit = MESSAGE_TYPES[message_type]
    if scalar_kind(entry) != native_kind:
        raise ValueError(f'{message_type} requires a {native_kind} scalar attribute')
    if required_unit and (entry['si_unit'] != required_unit or entry['si_value'] is None):
        raise ValueError(f'{message_type} requires normalised {required_unit} units')
    output = scalar_output('', entry)
    if output is None:
        return None  # Invalid Bool/String: omit a reading without changing its type.
    _, reading, unit = output
    if kind == 'illuminance' and reading < 0:
        reading = math.nan
    return kind, reading, unit
