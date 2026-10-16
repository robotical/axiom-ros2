"""Shared driver and launch parameter defaults."""

import json
from pathlib import Path
import re

import yaml

from .core.ownership import endpoint_key, normalise_board_id

DEFAULT_PARAMETERS = {
    'transport': 'ws',
    'device_uri': '',
    'auto_connect': True,
    'auto_reconnect': True,
    'reconnect_interval': 2.0,
    'frame_id': 'axiom',
    'sensor_frames': '{}',
    'topic_aliases': '{}',
    'ws_pcol': 'RICSerial',
    'serial.port': '',
    'serial.baud': 115200,
    'serial.timeout': 0.02,
    'serial.mode': 'auto',
    'autosub': True,
    'publish_rate_hz': 10.0,
    'publish_trigger': 'time',
    'rpc_default_timeout': 3.0,
    'sensor_qos.reliability': 'best_effort',
    'sensor_qos.depth': 10,
    'sensor_qos.overrides': '{}',
    'publish_custom_messages': True,
    'range.field_of_view': 0.0,
    'metadata_refresh_s': 30.0,
    'receive_queue_depth': 256,
    'stale_after_s': 5.0,
}


def board_parameters(namespace, values):
    """Validate shared parameter types and derive a distinct board frame prefix."""
    if not re.fullmatch(r'/[A-Za-z_][A-Za-z0-9_]*(/[A-Za-z_][A-Za-z0-9_]*)*', namespace):
        raise ValueError(f'Invalid board namespace: {namespace}')
    if not isinstance(values, dict) or set(values) - DEFAULT_PARAMETERS.keys():
        raise ValueError(f'Invalid driver parameters for {namespace}')
    params = {**DEFAULT_PARAMETERS, 'frame_id': namespace.strip('/').replace('/', '_'), **values}
    for key in ('topic_aliases', 'sensor_frames', 'sensor_qos.overrides'):
        if isinstance(params[key], dict):
            params[key] = json.dumps(params[key])
    for key, default in DEFAULT_PARAMETERS.items():
        value = params[key]
        if type(value) is not type(default):
            if isinstance(default, float) and type(value) is int:
                params[key] = float(value)
            else:
                raise ValueError(f'{namespace}: {key} must be {type(default).__name__}')
    return params


def load_boards(filename):
    """Read the same board parameters for single/multiple launches and the guide."""
    config = yaml.safe_load(Path(filename).expanduser().read_text())
    rows = config.get('axioms') if isinstance(config, dict) else None
    if not isinstance(rows, dict) or not rows:
        raise ValueError('boards_file must contain a nonempty axioms mapping')
    boards, frames, connections = {}, set(), set()
    for namespace, values in rows.items():
        name = '/' + str(namespace).strip('/')
        params = board_parameters(name, values)
        frame = params['frame_id']
        connection = (params['transport'], params['serial.port']
                      if params['transport'] == 'serial' else params['device_uri'])
        if name in boards or frame in frames or connection in connections:
            raise ValueError('Each board needs a unique namespace, frame_id and connection')
        frames.add(frame)
        connections.add(connection)
        boards[name] = params
    return boards


def load_discovery_config(filename):
    """Read optional identity/endpoint rules from the existing board file format."""
    settings = {'usb': True, 'wifi': True, 'include_unconfigured': True}
    if not filename:
        return settings, {}
    config = yaml.safe_load(Path(filename).expanduser().read_text())
    if not isinstance(config, dict) or set(config) - {'discovery', 'axioms'}:
        raise ValueError('Expected discovery and/or axioms mappings in boards_file')
    options, rows = config.get('discovery', {}), config.get('axioms', {})
    if not isinstance(options, dict) or set(options) - settings.keys():
        raise ValueError('Unknown discovery setting')
    if any(type(value) is not bool for value in options.values()):
        raise ValueError('Discovery settings must be booleans')
    settings.update(options)
    if not isinstance(rows, dict):
        raise ValueError('axioms must be a mapping')
    rules, identities, endpoints, frames = {}, set(), set(), set()
    for namespace, values in rows.items():
        name = '/' + str(namespace).strip('/')
        if not isinstance(values, dict):
            raise ValueError(f'Invalid board configuration for {name}')
        parameters = {key: value for key, value in values.items() if key != 'id'}
        params = board_parameters(name, parameters)
        identity = normalise_board_id(values.get('id'))
        if 'id' in values and identity is None:
            raise ValueError(f'{name}: id must be a 12-digit firmware MAC')
        transport = values.get('transport')
        if transport is not None and transport not in ('serial', 'ws'):
            raise ValueError(f'{name}: transport must be serial or ws')
        if values.get('serial.port') and values.get('device_uri'):
            raise ValueError(f'{name}: configure one endpoint, or use id for either transport')
        address = values.get('serial.port') or values.get('device_uri')
        if address:
            inferred = 'serial' if values.get('serial.port') else 'ws'
            if transport is not None and transport != inferred:
                raise ValueError(f'{name}: transport does not match its endpoint')
            transport = inferred
        if not identity and not address:
            raise ValueError(f'{name}: set id or an explicit endpoint')
        endpoint = endpoint_key(transport, address) if address else None
        if (name in rules or params['frame_id'] in frames
                or identity and identity in identities or endpoint and endpoint in endpoints):
            raise ValueError('Board namespace, frame_id, identity and endpoint must be unique')
        identities.add(identity)
        endpoints.add(endpoint)
        frames.add(params['frame_id'])
        rules[name] = {
            'id': identity, 'transport': transport, 'address': address,
            'endpoint': endpoint, 'parameters': params,
        }
    return settings, rules
