"""Readable topics retain sensor model, physical location and payload group."""

from axiom_driver.core.registry import Device, DeviceKey, DeviceRegistry
from axiom_driver.core.topic_names import image_suffix, measurement_topic, sensor_topic
import pytest


@pytest.mark.parametrize('model,suffix,expected', [
    ('VL53L4CD', 'range', 'vl53l4cd_b1_129/range'),
    ('LSM6DS', 'data_raw', 'lsm6ds_b1_129/data_raw'),
    ('AMG8833', 'image', 'amg8833_b1_129/image'),
    ('AMG8833', 'grid', 'amg8833_b1_129/grid'),
    ('VL53L5CX', 'image', 'vl53l5cx_b1_129/image'),
    ('VL53L4CD', 'range/raw', 'vl53l4cd_b1_129/range/raw'),
    ('LSM6DS', 'imu/axiom', 'lsm6ds_b1_129/imu/axiom'),
    ('RoboticalVCP', 'power/raw', 'roboticalvcp_b1_129/power/raw'),
    ('LTR-390', 'sample', 'ltr_2d390_b1_129/sample'),
    ('LTR_390', 'data', 'ltr_5f390_b1_129/data'),
    ('123 Sensor', 'sample', 'sensor_123_20sensor_b1_129/sample'),
])
def test_readable_output_contract(model, suffix, expected):
    device = Device(DeviceKey('1', '129'), model, 1, metadata={'type': model})
    assert measurement_topic(device, 'x', suffix) == expected
    assert device.key.frame_suffix == 'bus_1_device_129'


def test_duplicate_sensors_keep_names_as_peers_come_and_go():
    keys = [DeviceKey('1', '29'), DeviceKey('1', '129'), DeviceKey('2', '29')]
    expected = ['vl53l4cd_b1_29', 'vl53l4cd_b1_129', 'vl53l4cd_b2_29']
    assert [sensor_topic('VL53L4CD', key) for key in keys] == expected
    assert len(set(expected)) == 3
    for peers in (keys[:1], keys[::-1], keys[1:], keys):
        for key in peers:
            assert sensor_topic('VL53L4CD', key) == expected[keys.index(key)]


def test_escaped_bus_and_payload_groups_do_not_collapse():
    device = Device(DeviceKey('i2c/1', '29'), 'LSM6DS', 1)
    first = measurement_topic(device, 'a/b', 'data_raw')
    second = measurement_topic(device, 'a_2fb', 'data_raw')
    assert first == 'lsm6ds_bi2c_2f1_29/group_a_2fb/data_raw'
    assert second == 'lsm6ds_bi2c_2f1_29/group_a_5f2fb/data_raw'
    assert measurement_topic(device, 'x', 'data_raw') == 'lsm6ds_bi2c_2f1_29/data_raw'


def test_dual_image_names_follow_descriptor_independent_of_arrival_order():
    device = Device(DeviceKey('1', '29'), 'CombinedGrid', 1, metadata={
        'type': 'CombinedGrid', 'resp': {'a': [
            {'n': 'dist', 'vt': 'zonegrid'},
            {'n': 'temperature', 'resolution': '8x8'},
        ]}})
    expected = {'range/image': 'combinedgrid_b1_29/range/image',
                'thermal/image': 'combinedgrid_b1_29/thermal/image'}
    # The helper does not depend on samples, previously observed outputs or peers.
    for outputs in (('range/image',), ('thermal/image',),
                    ('range/image', 'thermal/image'), ('thermal/image', 'range/image')):
        for suffix in outputs:
            assert image_suffix(device, suffix.split('/')[0]) == suffix
            assert measurement_topic(device, 'x', suffix) == expected[suffix]


def test_inventory_waits_for_metadata_before_assigning_a_public_root(catalogue):
    registry = DeviceRegistry()
    device = Device(DeviceKey('1', '29'), 1, 1, last_seen=1.0)
    registry.devices[device.key] = device
    unresolved = registry.snapshot(1.0)[0]
    assert unresolved['topic'] is None and not unresolved['metadata_ready']
    assert unresolved['bus'] == '1' and unresolved['address'] == '29'
    assert registry.install(device.key, 1, {'devinfo': catalogue['VL53L4CD'], 'dtIdx': 1})
    ready = registry.snapshot(1.0)[0]
    assert ready['topic'] == 'vl53l4cd_b1_29' and ready['metadata_ready']
