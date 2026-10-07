"""Shared driver and launch parameter defaults."""

import json
from pathlib import Path

import yaml

DEFAULT_PARAMETERS = {
    'transport': 'ws',
    'device_uri': 'ws://192.168.1.7/ws',
    'auto_connect': False,
    'auto_reconnect': False,
    'reconnect_interval': 2.0,
    'frame_id': 'axiom',
    'sensor_frames': '{}',
    'topic_aliases': '{}',
    'ws_pcol': 'RICSerial',
    'serial.port': '/dev/ttyUSB0',
    'serial.baud': 115200,
    'serial.timeout': 0.02,
    'serial.mode': 'auto',
    'autosub': False,
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


def load_boards(filename):
    """Read the same board parameters for single/multiple launches and the guide."""
    config = yaml.safe_load(Path(filename).expanduser().read_text())
    rows = config.get('axioms') if isinstance(config, dict) else None
    if not isinstance(rows, dict) or not rows:
        raise ValueError('boards_file must contain a nonempty axioms mapping')
    boards, frames, connections = {}, set(), set()
    for namespace, values in rows.items():
        name = '/' + str(namespace).strip('/')
        if name == '/' or not isinstance(values, dict) or set(values) - DEFAULT_PARAMETERS.keys():
            raise ValueError(f'Invalid driver parameters for {name}')
        params = {**DEFAULT_PARAMETERS, 'frame_id': name.strip('/').replace('/', '_'), **values}
        for key in ('topic_aliases', 'sensor_frames', 'sensor_qos.overrides'):
            if isinstance(params[key], dict):
                params[key] = json.dumps(params[key])
        for key, default in DEFAULT_PARAMETERS.items():
            value = params[key]
            if type(value) is not type(default):
                if isinstance(default, float) and type(value) is int:
                    params[key] = float(value)
                else:
                    raise ValueError(f'{name}: {key} must be {type(default).__name__}')
        frame = params['frame_id']
        connection = (params['transport'], params['serial.port']
                      if params['transport'] == 'serial' else params['device_uri'])
        if name in boards or frame in frames or connection in connections:
            raise ValueError('Each board needs a unique namespace, frame_id and connection')
        frames.add(frame)
        connections.add(connection)
        boards[name] = params
    return boards
