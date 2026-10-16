"""Adapter contracts for additional readable paths and existing consumers."""

import copy
import struct
from types import SimpleNamespace

import pytest

rclpy = pytest.importorskip('rclpy')
from axiom_driver.core.decoding import SampleDecoder  # noqa: E402,I100
from axiom_driver.core.registry import Device, DeviceKey, DeviceRegistry  # noqa: E402
from axiom_driver.core.topic_names import sensor_topic  # noqa: E402
from axiom_driver.ros_adapters import RosAdapters  # noqa: E402
from rclpy.qos import QoSProfile, ReliabilityPolicy  # noqa: E402
from rclpy.serialization import serialize_message  # noqa: E402
from rclpy.topic_or_service_is_hidden import topic_or_service_is_hidden  # noqa: E402
from rclpy.validate_full_topic_name import validate_full_topic_name  # noqa: E402


class RecordingNode:
    """Record ROS-typed messages and exact publisher retirement without DDS timing."""

    def __init__(self):
        self.publishers = []

    def create_publisher(self, msg_type, topic, qos):
        publisher = SimpleNamespace(topic=topic, msg_type=msg_type, qos_profile=qos,
                                    messages=[], destroyed=False)
        publisher.publish = lambda msg: publisher.messages.append(copy.deepcopy(msg))
        self.publishers.append(publisher)
        return publisher

    def destroy_publisher(self, publisher):
        assert not publisher.destroyed
        publisher.destroyed = True

    def active(self, topic):
        return [p for p in self.publishers if p.topic == topic and not p.destroyed]


def range_device(address='29', revision=1, model='VL53L4CD'):
    return Device(DeviceKey('1', address), model, revision,
                  metadata={'type': model}, last_seen=1.0)


def inventory(*devices):
    registry = DeviceRegistry()
    registry.devices = {device.key: device for device in devices}
    return registry.snapshot(1.0)


def sample(distance=.25):
    return {'stamp_ns': 1_000_000_123, 'receipt_ns': 1_000_000_456,
            'timestamp_us': 100, 'poll_timestamp_us': 100, 'timestamp_ms': .1,
            'time_quality': 'device', 'overflow': 0,
            'values': {'dist': {'si_unit': 'm', 'si_value': distance,
                                'value': distance * 1000, 'raw': int(distance * 1000),
                                'valid': True, 'unit': 'mm', 'meta': {'r': [0, 4000]}}}}


@pytest.mark.parametrize('model', [
    '123 Sensor', '#sensor', 'µsensor', '温度', '_sensor', 'A/B', 'A_B', 'A-5',
])
def test_unusual_model_topics_are_valid_and_visible(model):
    topic = '/axiom/' + sensor_topic(model, DeviceKey('bus/1', '29')) + '/sample'
    validate_full_topic_name(topic)
    assert not topic_or_service_is_hidden(topic)


def test_messages_inventory_and_payload_groups_preserve_data_and_frame_contracts():
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10), frame_prefix='robot', topic_aliases={
        'front/range': {'type': 'VL53L4CD', 'source': 'range'}})
    device = range_device()
    rows = inventory(device)
    adapter.sync(rows)
    assert rows[0]['public_topics'] == {}
    adapter.publish(device, 'x', sample())
    rows = inventory(device)
    adapter.sync(rows)
    assert rows[0]['topic'] == 'vl53l4cd_b1_29'
    assert rows[0]['aliases'] == ['front/range']
    assert rows[0]['public_topics'] == {'x': {
        'sample': 'vl53l4cd_b1_29/sample', 'data': 'vl53l4cd_b1_29/data',
        'range': 'vl53l4cd_b1_29/range', 'range/raw': 'vl53l4cd_b1_29/range/raw'}}
    original = node.active('vl53l4cd_b1_29/range')[0].messages[-1]
    assert serialize_message(node.active('front/range')[0].messages[-1]) == (
        serialize_message(original))
    assert {publisher.topic for publisher in node.publishers} == {
        'vl53l4cd_b1_29/sample', 'vl53l4cd_b1_29/data', 'vl53l4cd_b1_29/range',
        'vl53l4cd_b1_29/range/raw', 'front/range'}
    assert original.header.frame_id == 'robot_bus_1_device_29'
    assert original.header.stamp.sec == 1 and original.header.stamp.nanosec == 123

    adapter.publish(device, 'fifo/2', sample(.5))
    adapter.sync(rows)
    assert rows[0]['public_topics']['fifo/2']['range'] == (
        'vl53l4cd_b1_29/group_fifo_2f2/range')
    assert node.active('vl53l4cd_b1_29/group_fifo_2f2/range')[0].messages[-1].range == .5
    assert len(node.active('front/range')[0].messages) == 1
    assert node.active('vl53l4cd_b1_29/range')[0].messages[-1].range == .25


@pytest.mark.parametrize('retirement', ['offline', 'stale', 'unresolved',
                                        'revision', 'removal', 'reset'])
def test_readable_publishers_retire_and_replug_at_same_names(retirement):
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10))
    device = range_device()
    adapter.sync(inventory(device))
    adapter.publish(device, 'x', sample())
    paths = [p.topic for p in node.publishers]
    rows = inventory(device)
    if retirement == 'offline':
        rows[0]['online'] = False
    elif retirement == 'stale':
        rows[0]['stale'] = True
    elif retirement == 'unresolved':
        rows[0]['metadata_ready'] = False
    elif retirement == 'revision':
        device.revision += 1
        rows = inventory(device)
    else:
        rows = []
    adapter.sync(rows)
    assert all(not node.active(path) for path in paths)
    assert all(row['public_topics'] == {} for row in rows)
    assert not adapter.public_topics
    adapter.sync(inventory(device))
    adapter.publish(device, 'x', sample())
    assert all(len(node.active(path)) == 1 for path in paths)


def test_metadata_model_replacement_retires_old_names_before_new_publications():
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10), custom_messages=False)
    old = range_device()
    adapter.sync(inventory(old))
    adapter.publish(old, 'x', sample())
    replacement = range_device(revision=2, model='NewDistance')
    rows = inventory(replacement)
    adapter.sync(rows)
    assert not node.active('vl53l4cd_b1_29/range')
    assert rows[0]['public_topics'] == {}
    adapter.publish(replacement, 'x', sample())
    adapter.sync(rows)
    assert rows[0]['public_topics']['x']['range'] == 'newdistance_b1_29/range'
    assert not node.active('bus_1/device_29/range')
    assert node.active('newdistance_b1_29/range')


def test_inventory_does_not_advertise_unsupported_sensor_mappings():
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10), custom_messages=False)
    device = range_device(model='LSM6DS')
    adapter.sync(inventory(device))
    generic = sample()
    generic['values'] = {'unknown': generic['values']['dist']}
    adapter.publish(device, 'x', generic)
    rows = inventory(device)
    adapter.sync(rows)
    assert set(rows[0]['public_topics']['x']) == {'sample', 'data'}
    assert not node.active('lsm6ds_b1_29/data_raw')
    assert not node.active('lsm6ds_b1_29/range')


def test_dual_grid_descriptor_keeps_both_image_meanings_on_distinct_stable_topics(grid_profiles):
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10), custom_messages=False)
    thermal = grid_profiles['AMG8833']['resp']
    ranging = grid_profiles['VL53L5CX']['resp']
    device = range_device(model='CombinedGrid')
    device.metadata['resp'] = {'a': ranging['a'] + thermal['a']}
    adapter.sync(inventory(device))
    decoder = SampleDecoder()
    thermal_values = decoder.values(struct.pack('<64h', *([100] * 64)), thermal)[0][0]
    range_payload = bytes([4, 1, 25, 3]) + struct.pack('<64h', *([1000] * 64)) + bytes([5] * 64)
    range_values = decoder.values(range_payload, ranging)[0][0]
    for values in (range_values, thermal_values, {**range_values, **thermal_values}):
        measurement = sample()
        measurement['values'] = values
        adapter.publish(device, 'x', measurement)
    rows = inventory(device)
    adapter.sync(rows)
    paths = rows[0]['public_topics']['x']
    assert paths['range/image'] == 'combinedgrid_b1_29/range/image'
    assert paths['thermal/image'] == 'combinedgrid_b1_29/thermal/image'
    assert not node.active('combinedgrid_b1_29/image')
    for suffix, width in (('range/image', 4), ('thermal/image', 8)):
        readable = node.active(paths[suffix])[0].messages
        assert len(readable) == 2
        assert not node.active('bus_1/device_29/' + suffix)
        assert all(message.width == width for message in readable)
        assert all(message.header.frame_id == 'axiom_bus_1_device_29' for message in readable)
        pixel = struct.unpack('<f', bytes(readable[-1].data[:4]))[0]
        assert pixel == (1.0 if width == 4 else 25.0)


def test_existing_alias_reserves_readable_path_before_and_after_its_source_disappears():
    node = RecordingNode()
    path = 'vl53l4cd_b1_29/range'
    adapter = RosAdapters(node, QoSProfile(depth=10), topic_aliases={
        path: {'type': 'VL53L4CD', 'source': 'range', 'address': '129'}})
    first, second = range_device(), range_device('129')
    adapter.sync(inventory(first, second))
    adapter.publish(first, 'x', sample(.1))
    assert not node.active(path)
    adapter.publish(second, 'x', sample(.2))
    assert len(node.active(path)) == 1
    assert [msg.range for msg in node.active(path)[0].messages] == [.2]
    rows = inventory(first, second)
    adapter.sync(rows)
    assert 'range' not in rows[0]['public_topics']['x']
    second.online = False
    adapter.sync(inventory(first, second))
    adapter.publish(first, 'x', sample(.3))
    assert not node.active(path), 'An unbound configured alias still reserves its exact path'
    assert not node.active('bus_1/device_29/range')
    assert len(node.active('vl53l4cd_b1_29/sample')[0].messages) == 2


@pytest.mark.parametrize('alias,retire', [
    ('vl53l4cd_b1_29/range/extra', 'first'),
    ('vl53l4cd_b1_29', 'second'),
])
def test_exact_retirement_preserves_independently_owned_parent_or_child(alias, retire):
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10), topic_aliases={
        alias: {'type': 'VL53L4CD', 'source': 'range', 'address': '129'}})
    first, second = range_device(), range_device('129')
    adapter.sync(inventory(first, second))
    adapter.publish(first, 'x', sample(.1))
    adapter.publish(second, 'x', sample(.2))
    assert node.active(alias) and node.active('vl53l4cd_b1_29/range')
    (first if retire == 'first' else second).online = False
    adapter.sync(inventory(first, second))
    survivor = alias if retire == 'first' else 'vl53l4cd_b1_29/range'
    assert len(node.active(survivor)) == 1
    assert not node.active('vl53l4cd_b1_29/range' if retire == 'first' else alias)


@pytest.mark.parametrize('explicit_readable_override', [False, True])
def test_qos_matches_only_current_paths_and_old_keys_have_no_effect(
    explicit_readable_override,
):
    node = RecordingNode()
    source = 'bus_1/device_29/range'
    readable = 'vl53l4cd_b1_29/range'
    overrides = {source: {'depth': 3, 'reliability': 'reliable'},
                 'front/range': {'depth': 2, 'reliability': 'reliable'}}
    if explicit_readable_override:
        overrides[readable] = {'depth': 7, 'reliability': 'reliable'}
    adapter = RosAdapters(node, QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT),
                          qos_overrides=overrides, topic_aliases={
                              'front/range': {'type': 'VL53L4CD', 'source': 'range'}})
    device = range_device()
    adapter.sync(inventory(device))
    adapter.publish(device, 'x', sample())
    assert not node.active(source)
    public = node.active(readable)[0].qos_profile
    alias = node.active('front/range')[0].qos_profile
    assert alias.depth == 2 and alias.reliability == ReliabilityPolicy.RELIABLE
    assert public.depth == (7 if explicit_readable_override else 10)
    assert public.reliability == (ReliabilityPolicy.RELIABLE if explicit_readable_override
                                  else ReliabilityPolicy.BEST_EFFORT)
