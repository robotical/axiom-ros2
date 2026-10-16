"""Standard scalar ROS contracts, aliases, inventory and publisher lifetime."""

import json
import math
import struct

import pytest

rclpy = pytest.importorskip('rclpy')
from axiom_driver.core.decoding import SampleDecoder  # noqa: E402,I100
from axiom_driver.core.registry import Device, DeviceKey  # noqa: E402
from axiom_driver.ros_adapters import RosAdapters  # noqa: E402
from rclpy.qos import QoSProfile, ReliabilityPolicy  # noqa: E402
from rclpy.serialization import serialize_message  # noqa: E402
from sensor_msgs.msg import Illuminance  # noqa: E402
from std_msgs.msg import Bool, Float64, String  # noqa: E402
from test_readable_topics_ros import inventory, RecordingNode, sample  # noqa: E402


def publish_profile(adapter, profile, payload, address='53', revision=1, group='x'):
    device = Device(DeviceKey('1', address), profile['type'], revision,
                    metadata=profile, last_seen=1.)
    measurement = sample()
    measurement['values'] = SampleDecoder().values(payload, profile['resp'], profile['type'])[0][0]
    adapter.sync(inventory(device))
    adapter.publish(device, group, measurement)
    rows = inventory(device)
    adapter.sync(rows)
    return device, rows[0]


def test_ltr390_messages_units_frame_alias_qos_and_retirement(catalogue):
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10), custom_messages=False,
                          topic_aliases={'uv': {'type': 'LTR-390', 'source': 'UVI'}},
                          qos_overrides={'uv': {'depth': 2, 'reliability': 'reliable'},
                                         'ltr_2d390_b1_53/ambient': {'depth': 3}})
    device, row = publish_profile(adapter, catalogue['LTR-390'], bytes.fromhex('7d00003000'))
    root = row['topic']
    light = node.active(root + '/ambient')[0]
    uv = node.active(root + '/UVI')[0]
    alias = node.active('uv')[0]
    assert light.msg_type is Illuminance and light.qos_profile.depth == 3
    assert light.messages[-1].illuminance == 100.
    assert light.messages[-1].variance == 0.
    assert light.messages[-1].header.frame_id == 'axiom_bus_1_device_53'
    assert light.messages[-1].header.stamp.sec == 1
    assert light.messages[-1].header.stamp.nanosec == 123
    assert uv.msg_type is Float64 and uv.messages[-1].data == 2.
    assert serialize_message(alias.messages[-1]) == serialize_message(uv.messages[-1])
    assert alias.qos_profile.depth == 2
    assert alias.qos_profile.reliability == ReliabilityPolicy.RELIABLE
    assert row['public_topics']['x'] == {
        suffix: root + '/' + suffix for suffix in ('sample', 'data', 'ambient', 'UVI')}
    assert row['output_info']['x']['ambient'] == {
        'message_type': 'sensor_msgs/msg/Illuminance', 'unit': 'lux'}
    assert row['output_info']['x']['UVI'] == {
        'message_type': 'std_msgs/msg/Float64', 'unit': 'index'}
    decoded = json.loads(node.active(root + '/sample')[0].messages[-1].values_json)
    assert decoded['ambient']['raw'] == 125 and decoded['UVI']['value'] == 2.
    assert 'values' in json.loads(node.active(root + '/data')[0].messages[-1].data)

    # Revision changes retire both canonical and aliased publishers and metadata.
    device.revision += 1
    rows = inventory(device)
    adapter.sync(rows)
    assert all(p.destroyed for p in node.publishers)
    assert rows[0]['public_topics'] == {} and rows[0]['output_info'] == {}
    publish_profile(adapter, catalogue['LTR-390'], bytes.fromhex('fa00006000'), revision=2)
    assert node.active('uv')[0].messages[-1].data == 4.
    adapter.sync([])
    assert all(p.destroyed for p in node.publishers)
    assert not adapter.public_topics and not adapter.output_info


def test_invalid_boolean_and_text_readings_do_not_create_float_publishers():
    profile = {'type': 'LibrarySensor', 'resp': {'a': [
        {'n': 'ready', 't': 'B', 'o': 'bool', 'vft': 'valid'},
        {'n': 'label', 't': '4s', 'vft': 'valid'},
        {'n': 'amount', 't': '<H', 'd': 2, 'vft': 'valid'},
        {'n': 'valid', 't': 'B', 'o': 'bool'}]}}
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10))
    for valid in (0, 1, 0):
        _, row = publish_profile(adapter, profile, b'\x01abc\0\x05\x00' + bytes([valid]))
        root = row['topic']
        assert node.active(root + '/amount')[0].msg_type is Float64
        if not valid:
            assert math.isnan(node.active(root + '/amount')[0].messages[-1].data)
        else:
            assert node.active(root + '/amount')[0].messages[-1].data == 2.5
    assert node.active(root + '/ready')[0].msg_type is Bool
    assert [msg.data for msg in node.active(root + '/ready')[0].messages] == [True]
    assert node.active(root + '/label')[0].msg_type is String
    assert [msg.data for msg in node.active(root + '/label')[0].messages] == ['abc']
    assert len(node.active(root + '/amount')) == 1


def test_scalar_names_cannot_collide_with_generic_or_image_outputs():
    profile = {'type': 'LibrarySensor', 'resp': {'a': [
        {'n': 'data', 't': 'B'}, {'n': 'sample', 't': 'B'},
        {'n': 'image', 't': 'B'}, {'n': '1st', 't': 'B'}, {'n': 'A/B', 't': 'B'},
        {'n': 'A_B', 't': 'B'}]}}
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10))
    _, row = publish_profile(adapter, profile, bytes(range(6)), group='fifo/2')
    outputs = row['public_topics']['fifo/2']
    assert set(outputs) == {'sample', 'data', 'attribute_data', 'attribute_sample',
                            'attribute_image', 'attribute_1st', 'A_2fB', 'A_5fB'}
    assert len({p.topic for p in node.publishers}) == len(node.publishers)
    assert all('/group_fifo_2f2/' in topic for topic in outputs.values())


@pytest.mark.parametrize('model,payload,absent', [
    ('LSM6DS', bytes([6, 0, 0, 0]) + struct.pack('<6h', *([1] * 6)),
     {'gx', 'gy', 'gz', 'ax', 'ay', 'az'}),
    ('VL53L4CD', bytes.fromhex('000064'), {'dist', 'valid'}),
    ('TMP117', struct.pack('>h', 20000), {'temperature'}),
])
def test_existing_adapters_take_priority_over_component_scalar_outputs(
    catalogue, model, payload, absent,
):
    profile = catalogue[model]
    payload = payload.ljust(profile['resp']['b'], b'\0')
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10), custom_messages=False)
    _, row = publish_profile(adapter, profile, payload)
    # Temperature/humidity retain their semantic types at the existing suffixes.
    for suffix in absent:
        assert row['output_info']['x'].get(suffix, {}).get('message_type') != (
            'std_msgs/msg/Float64')
    assert len(node.publishers) >= 3


def test_grids_keep_arrays_in_generic_outputs_and_consume_dimension_attribute(grid_profiles):
    profile = grid_profiles['VL53L5CX']
    payload = bytes([4, 1, 25, 16]) + struct.pack('<64h', *([1000] * 64)) + bytes([5] * 64)
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10), custom_messages=False)
    _, row = publish_profile(adapter, profile, payload)
    outputs = row['public_topics']['x']
    assert set(outputs) == {'sample', 'data', 'image', 'seq', 'tempC', 'nValid'}
    assert row['output_info']['x']['tempC']['unit'] == 'degC'
    assert row['output_info']['x']['image']['unit'] == 'm'
    assert all(p.msg_type is not Float64 for p in node.active(row['topic'] + '/dist'))


def test_only_the_selected_range_and_battery_attributes_are_consumed():
    profile = {'type': 'LibrarySensor', 'resp': {'a': [
        {'n': 'dist', 't': '<H', 'u': 'mm'}, {'n': 'distance', 't': '<H', 'u': 'mm'},
        {'n': 'battV', 't': '<f', 'u': 'V'}, {'n': 'batteryVoltage', 't': '<f', 'u': 'V'}]}}
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10), custom_messages=False)
    _, row = publish_profile(adapter, profile, struct.pack('<HHff', 100, 200, 3.5, 4.5))
    root = row['topic']
    assert node.active(root + '/range')[0].messages[-1].range == pytest.approx(.1)
    assert node.active(root + '/distance')[0].messages[-1].data == pytest.approx(.2)
    assert node.active(root + '/battery')[0].messages[-1].voltage == 3.5
    assert node.active(root + '/batteryVoltage')[0].messages[-1].data == 4.5
    assert not node.active(root + '/dist') and not node.active(root + '/battV')
