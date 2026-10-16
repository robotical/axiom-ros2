"""Public sensor paths, separate from firmware bus/address and frame identities."""

from .registry import topic_token


def sensor_topic(device_type, key):
    """Keep model and firmware location stable regardless of discovery order."""
    model = topic_token(device_type.lower())
    if not model[0].isalpha():
        model = 'sensor_' + model
    return f'{model}_b{topic_token(key.bus)}_{topic_token(key.address)}'


def measurement_topic(device, group, suffix):
    """Build the public path for one measurement output and payload group."""
    base = sensor_topic(device.device_type, device.key)
    if group != 'x':
        base += '/group_' + topic_token(group)
    return base + '/' + suffix


def image_suffix(device, measurement):
    """Keep dual-grid meanings separate based on descriptor capabilities."""
    attrs = device.metadata.get('resp', {}).get('a', [])
    range_grid = any(a.get('n') in ('dist', 'distance') and a.get('vt') == 'zonegrid'
                     for a in attrs)
    thermal_grid = any(a.get('n') == 'temperature' and 'x' in a.get('resolution', '')
                       for a in attrs)
    return measurement + '/image' if range_grid and thermal_grid else 'image'
