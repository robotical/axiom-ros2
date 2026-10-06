"""Descriptor argument contracts and alias selection under hot swapping."""

import copy
import time
from urllib.parse import parse_qs, urlsplit

from axiom_driver.core.aliases import bindings, validate_aliases
from axiom_driver.core.commands import encode_command
from axiom_driver.core.pipeline import Pipeline
from axiom_driver.core.registry import DeviceKey
from axiom_driver.core.timing import Receipt
import pytest


def test_led_and_servo_encoding_matches_descriptor(catalogue):
    led = {a['n']: a for a in catalogue['QwiicLEDStick']['actions']}
    assert encode_command(led['brightness'], [50]) == ['7632']
    assert encode_command(led['off'], []) == ['78']
    assert encode_command(led['pixels'], [9, 255, 0, 128]) == ['7109ff0080']
    servo = catalogue['RoboticalServo']['actions'][0]
    assert encode_command(servo, [-12.5]) == ['0001ff830064']
    with pytest.raises(ValueError, match='grid'):
        encode_command(led['pixels'], [10, 1, 2, 3])
    for invalid in ([256], [-1], [1.5], [float('nan')], []):
        with pytest.raises(ValueError):
            encode_command(led['brightness'], invalid)
    assert encode_command({'w': '0100', 'wz': '&p100&02'}, []) == ['0100', .1, '02']


def test_output_device_discovery_and_retired_command(catalogue):
    calls, samples, errors = [], [], []

    def request(path):
        calls.append(path)
        if 'typeinfo' in path:
            return {'rslt': 'ok', 'dtIdx': 1, 'devinfo': catalogue['QwiicLEDStick']}
        return {'rslt': 'ok'}
    p = Pipeline(request, lambda *a: samples.append(a), on_error=errors.append)
    now = time.monotonic()
    packet = {'1': {'23': {'_i': 1, '_o': 1, 'x': ''}}}
    p.process(packet, Receipt(now, 1))
    device = p.registry.devices[DeviceKey('1', '23')]
    assert device.metadata and not samples and not errors
    p.command(device.key, device.revision, 'brightness', [50], 5)
    query = parse_qs(urlsplit(calls[-1]).query)
    assert query == {'deviceid': ['1_23'], 'hexWr': ['7632']}
    old_revision = device.revision
    p.process({'1': {'23': {'_i': 1, '_o': 0}}}, Receipt(now + .1, 2))
    with pytest.raises(ValueError, match='offline'):
        p.command(device.key, old_revision, 'off', [], 5)
    p.process(packet, Receipt(now + .2, 3))
    with pytest.raises(ValueError, match='replaced'):
        p.command(device.key, old_revision, 'off', [], 5)


def test_aliases_do_not_merge_matching_devices():
    rules = validate_aliases({'range': {'type': 'VL53L4CD', 'source': 'range'}})
    row = {'topic': 'bus_1/device_29', 'revision': 1, 'type': 'VL53L4CD', 'bus': '1',
           'address': '29', 'online': True, 'stale': False, 'metadata_ready': True}
    assert bindings(rules, [row])['range'][0] == row['topic']
    other = {**row, 'topic': 'bus_1/device_129', 'address': '129'}
    assert not bindings(rules, [row, other])
    rules['range']['address'] = '129'
    assert bindings(rules, [row, other])['range'][0] == other['topic']
    assert not bindings(rules, [{**other, 'stale': True}])
    with pytest.raises(ValueError):
        validate_aliases({'devices': {'type': 'VL53L4CD', 'source': 'range'}})


def test_unchanged_profile_refresh_does_not_rotate_revision(catalogue):
    profile = copy.deepcopy(catalogue['VL53L4CD'])
    p = Pipeline(lambda _: {'rslt': 'ok', 'dtIdx': 1, 'devinfo': profile},
                 lambda *a: None, metadata_refresh_s=1)
    packet = {'1': {'29': {'_i': 1, 'x': '0064000064'}}}
    p.process(packet, Receipt(1, 1))
    revision = p.registry.devices[DeviceKey('1', '29')].revision
    p.process(packet, Receipt(3, 3))
    assert p.registry.devices[DeviceKey('1', '29')].revision == revision
    profile['desc'] = 'Changed installed profile'
    p.process(packet, Receipt(5, 5))
    assert p.registry.devices[DeviceKey('1', '29')].revision > revision
