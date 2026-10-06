"""Firmware discovery to decoded samples, including failure/lifecycle paths."""

import copy
import json
from pathlib import Path

from axiom_driver.core.pipeline import Pipeline
from axiom_driver.core.registry import DeviceKey
from axiom_driver.core.timing import Receipt


def test_direct_power_device_uses_instance_metadata_and_decodes_board_capture():
    fixture = Path(__file__).parent / 'fixtures' / 'axiom_power_usb.json'
    capture = json.loads(fixture.read_text())
    calls, samples, errors = [], [], []

    def request(path):
        calls.append(path)
        return capture['metadata']

    pipeline = Pipeline(request, lambda *args: samples.append(args), on_error=errors.append)
    pipeline.process(capture['publication'], Receipt(1, 1_000_000_000))
    assert calls == ['devman/typeinfo?deviceid=0_1']
    assert not errors and len(samples) == 1
    device, group, reading = samples[0]
    assert device.name == 'Power' and device.role == 'system'
    assert device.device_type == 'RoboAxiomPowerV1' and group == 'x'
    assert reading['values']['battV']['si_value'] == 4.2
    assert reading['values']['usbPresent']['value'] == 1


def packet(type_ref=1, online=1, data='0064000064'):
    return {'_v': 1, '_t': 0, '1': {'29': {'_i': type_ref, '_o': online, 'x': data}}}


def test_first_packet_waits_for_metadata_without_being_lost(catalogue):
    calls, samples = [], []

    def request(path):
        calls.append(path)
        return {'rslt': 'ok', 'dtIdx': 1, 'devinfo': catalogue['VL53L4CD']}

    pipeline = Pipeline(request, lambda *args: samples.append(args))
    pipeline.process(packet(), Receipt(1, 1_000_000_000))
    assert calls == ['devman/typeinfo?bus=1&addr=0x29']
    assert len(samples) == 1
    assert samples[0][2]['values']['dist']['si_value'] == 0.1
    assert samples[0][2]['timestamp_us'] == 10000
    pipeline.process(packet(data='0065000064'), Receipt(1.001, 1_001_000_000))
    assert len(samples) == 2 and len(calls) == 1
    pipeline.process(packet(online=2, data=''), Receipt(2, 2_000_000_000))
    assert not pipeline.registry.devices and not pipeline.timelines
    assert not pipeline.refresh_at


def test_failed_metadata_is_retried_with_buffered_samples(catalogue):
    attempts, samples = [], []

    def request(path):
        attempts.append(path)
        if len(attempts) == 1:
            raise RuntimeError('temporarily unavailable')
        return {'rslt': 'ok', 'dtIdx': 1, 'devinfo': catalogue['VL53L4CD']}

    pipeline = Pipeline(request, lambda *args: samples.append(args))
    pipeline.process(packet(), Receipt(1, 1_000_000_000))
    assert not samples
    pipeline.process(packet(data='75300000c8'), Receipt(4, 4_000_000_000))
    assert len(samples) == 2
    assert samples[0][2]['receipt_ns'] == 1_000_000_000
    assert samples[1][2]['values']['dist']['si_value'] == 0.2


def test_session_change_during_lookup_drops_old_results(catalogue):
    current = [True]
    samples = []

    def request(path):
        current[0] = False
        return {'rslt': 'ok', 'dtIdx': 1, 'devinfo': catalogue['VL53L4CD']}

    pipeline = Pipeline(request, lambda *args: samples.append(args))
    pipeline.process(packet(), Receipt(1, 1), lambda: current[0])
    assert not samples
    pipeline.reset()
    assert not pipeline.registry.devices


def test_rate_configuration_uses_device_map_and_firmware_result(catalogue):
    calls = []

    def request(path):
        calls.append(path)
        return {'rslt': 'ok', 'sampleRateHz': 100, 'pollIntervalUs': 125000, 'numSamples': 8}

    pipeline = Pipeline(request, lambda *args: None)
    from axiom_driver.core.registry import parse_devjson

    record = parse_devjson(packet())[0]
    device, _ = pipeline.registry.observe(record, 1)
    device.metadata = copy.deepcopy(catalogue['RoboticalVCP'])
    response = pipeline.configure_rate(DeviceKey('1', '29'), 100)
    assert 'sampleRateHz=100' in calls[-1]
    assert response['pollIntervalUs'] == 125000
    assert pipeline.sample_periods[device.key] == 10000
