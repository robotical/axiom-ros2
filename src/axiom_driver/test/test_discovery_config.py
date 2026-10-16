"""Optional discovery rules reuse board parameters without requiring endpoints."""

import json

from axiom_driver.config import load_discovery_config
import pytest


ID_A = '001122334455'


def test_no_file_has_automatic_defaults_and_no_required_boards():
    settings, rules = load_discovery_config('')
    assert settings == {'usb': True, 'wifi': True, 'include_unconfigured': True}
    assert rules == {}


def test_identity_rules_normalise_mac_and_keep_parameter_types(tmp_path):
    path = tmp_path / 'boards.yaml'
    path.write_text(json.dumps({'discovery': {'include_unconfigured': False}, 'axioms': {
        'robot/front': {'id': '00:11:22:33:44:55', 'publish_rate_hz': 20,
                        'topic_aliases': {'range': {'type': 'VL53L4CD', 'source': 'range'}}},
        'rear': {'serial.port': '/dev/serial/by-id/rear'},
    }}))
    settings, rules = load_discovery_config(path)
    assert not settings['include_unconfigured']
    assert rules['/robot/front']['id'] == ID_A
    assert rules['/robot/front']['transport'] is None
    assert rules['/robot/front']['parameters']['frame_id'] == 'robot_front'
    assert rules['/robot/front']['parameters']['publish_rate_hz'] == 20.0
    assert json.loads(rules['/robot/front']['parameters']['topic_aliases'])['range']['type']
    assert rules['/rear']['transport'] == 'serial'


@pytest.mark.parametrize('config', [
    {'discovery': {'unknown': True}},
    {'discovery': {'wifi': 'false'}},
    {'axioms': []},
    {'axioms': {'front': {}}},
    {'axioms': {'front': {'id': 'invalid'}}},
    {'axioms': {'front': {'id': ID_A, 'unexpected': 1}}},
    {'axioms': {'1invalid': {'id': ID_A}}},
    {'axioms': {'front': {'id': ID_A}, 'rear': {'id': ID_A}}},
    {'axioms': {'a/b': {'id': ID_A}, 'a_b': {'id': 'aabbccddeeff'}}},
    {'axioms': {'front': {'id': ID_A, 'transport': 'bluetooth'}}},
    {'axioms': {'front': {'transport': 'ws', 'serial.port': '/virtual/a'}}},
    {'axioms': {'front': {'serial.port': '/virtual/a', 'device_uri': 'ws://192.0.2.1/ws'}}},
    {'axioms': {'front': {'device_uri': 'ws://192.0.2.1/ws'},
                'rear': {'device_uri': 'ws://192.0.2.1:80/other'}}},
])
def test_malformed_or_ambiguous_rules_fail_before_discovery_starts(tmp_path, config):
    path = tmp_path / 'boards.yaml'
    path.write_text(json.dumps(config))
    with pytest.raises(ValueError):
        load_discovery_config(path)
