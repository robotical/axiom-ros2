"""Explicit scalar ROS types preserve automatic mappings and publisher lifetime."""

import copy
import math
import struct

import pytest

rclpy = pytest.importorskip('rclpy')
from axiom_driver.core.decoding import SampleDecoder  # noqa: E402,I100
from axiom_driver.ros_adapters import RosAdapters  # noqa: E402
from rclpy.qos import QoSProfile, ReliabilityPolicy  # noqa: E402
from rclpy.serialization import serialize_message  # noqa: E402
from sensor_msgs.msg import Illuminance, RelativeHumidity, Temperature  # noqa: E402
from std_msgs.msg import Bool, Float64, String  # noqa: E402
from test_readable_topics_ros import inventory, RecordingNode, sample  # noqa: E402
from test_scalar_outputs_ros import publish_profile  # noqa: E402


def mapped_profile(attrs, mappings, model='LibrarySensor'):
    return {'type': model, 'resp': {'a': attrs}, 'ros': {'version': 1, 'attributes': {
        name: {'message_type': message_type} for name, message_type in mappings.items()}}}


def test_unfamiliar_scalar_names_select_semantic_types_with_frame_and_units():
    profile = mapped_profile([
        {'n': 'photodiode', 't': '<H', 'd': 2, 'u': 'lux'},
        {'n': 'tempC', 't': '<h', 'd': 4, 'u': '&deg;C'},
        {'n': 'RH', 't': '<H', 'd': 2, 'u': '%RH'},
        {'n': 'UVI', 't': '<H', 'd': 24, 'u': 'index'},
        {'n': 'unmapped', 't': 'B'},
    ], {'photodiode': 'sensor_msgs/msg/Illuminance', 'tempC': 'sensor_msgs/msg/Temperature',
        'RH': 'sensor_msgs/msg/RelativeHumidity', 'UVI': 'std_msgs/msg/Float64'})
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10),
                          topic_aliases={
                              'light': {'type': 'LibrarySensor', 'source': 'photodiode'}},
                          qos_overrides={'light': {'depth': 3, 'reliability': 'reliable'}})
    _, row = publish_profile(adapter, profile, struct.pack('<HhHHB', 200, -10, 84, 48, 7))
    root = row['topic']
    for suffix, message_type, field, expected, unit in (
        ('photodiode', Illuminance, 'illuminance', 100., 'lux'),
        ('tempC', Temperature, 'temperature', -2.5, 'degC'),
        ('RH', RelativeHumidity, 'relative_humidity', .42, 'fraction'),
        ('UVI', Float64, 'data', 2., 'index'),
        ('unmapped', Float64, 'data', 7., None),
    ):
        publisher = node.active(root + '/' + suffix)[0]
        assert publisher.msg_type is message_type
        assert getattr(publisher.messages[-1], field) == pytest.approx(expected)
        assert row['output_info']['x'][suffix]['unit'] == unit
        if message_type in (Illuminance, Temperature, RelativeHumidity):
            assert publisher.messages[-1].header.frame_id == 'axiom_bus_1_device_53'
            assert publisher.messages[-1].header.stamp.nanosec == 123
            assert publisher.messages[-1].variance == 0.
    alias = node.active('light')[0]
    assert alias.qos_profile.depth == 3
    assert alias.qos_profile.reliability == ReliabilityPolicy.RELIABLE
    assert serialize_message(alias.messages[-1]) == serialize_message(
        node.active(root + '/photodiode')[0].messages[-1])
    assert not node.warnings


def test_explicit_types_override_automatic_scalar_types_at_the_same_suffix():
    profile = mapped_profile([
        {'n': 'ambient', 't': '<H', 'u': 'lux'},
        {'n': 'temperature', 't': '<h', 'u': '&deg;C'},
        {'n': 'humidity', 't': '<H', 'u': '%'},
    ], {name: 'std_msgs/msg/Float64' for name in ('ambient', 'temperature', 'humidity')})
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10))
    _, row = publish_profile(adapter, profile, struct.pack('<HhH', 100, 25, 42))
    for suffix, expected in (('ambient', 100.), ('temperature', 25.), ('humidity', .42)):
        publishers = node.active(row['topic'] + '/' + suffix)
        assert len(publishers) == 1 and publishers[0].msg_type is Float64
        assert publishers[0].messages[-1].data == pytest.approx(expected)


def test_bad_mappings_warn_once_keep_fallbacks_and_do_not_block_valid_peers():
    profile = mapped_profile([
        {'n': 'ambient', 't': 'H', 'u': 'lux'},
        {'n': 'UVI', 't': 'H', 'u': 'index'},
        {'n': 'temperature', 't': 'h', 'u': '&deg;C'},
        {'n': 'ready', 't': 'B', 'o': 'bool'},
        {'n': 'label', 't': '4s'},
        {'n': 'extra', 't': 'B'},
    ], {'ambient': 'sensor_msgs/msg/Temperature', 'UVI': 'sensor_msgs/msg/Illuminance',
        'temperature': 'std_msgs/msg/Bool', 'ready': 'std_msgs/msg/Float64',
        'label': 'std_msgs/msg/Float64', 'extra': 'std_msgs/msg/Float64',
        'missing': 'std_msgs/msg/Float64'})
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10))
    payload = struct.pack('=HHhB4sB', 100, 2, 25, 1, b'abc\0', 7)
    for _ in range(3):
        device, row = publish_profile(adapter, profile, payload)
    assert len(node.warnings) == 6
    expected = {'ambient': Illuminance, 'UVI': Float64, 'temperature': Temperature,
                'ready': Bool, 'label': String, 'extra': Float64}
    for suffix, message_type in expected.items():
        publisher = node.active(row['topic'] + '/' + suffix)[0]
        assert publisher.msg_type is message_type and len(publisher.messages) == 3
    adapter.sync([])
    assert not adapter._mapping_state
    publish_profile(adapter, profile, payload, revision=device.revision + 1)
    assert len(node.warnings) == 12


def test_invalid_block_leaves_existing_ltr390_outputs_unchanged(catalogue):
    profile = copy.deepcopy(catalogue['LTR-390'])
    profile['ros'] = {'version': 99, 'attributes': {}}
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10))
    for _ in range(3):
        _, row = publish_profile(adapter, profile, bytes.fromhex('7d00003000'))
    assert len(node.warnings) == 1
    assert node.active(row['topic'] + '/ambient')[0].messages[-1].illuminance == 100.
    assert node.active(row['topic'] + '/UVI')[0].messages[-1].data == 2.


def test_revision_change_replaces_types_and_aliases_without_overlapping_publishers():
    original = mapped_profile([{'n': 'temperature', 't': 'h', 'u': '&deg;C'}], {})
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10), topic_aliases={
        'temp': {'type': 'LibrarySensor', 'source': 'temperature'}})
    device, row = publish_profile(adapter, original, struct.pack('=h', 25))
    old = node.active('temp')[0]
    changed = copy.deepcopy(original)
    changed['ros']['attributes']['temperature'] = {'message_type': 'std_msgs/msg/Float64'}
    _, row = publish_profile(adapter, changed, struct.pack('=h', 26), revision=device.revision + 1)
    assert old.destroyed and old.msg_type is Temperature
    assert len(node.active('temp')) == 1 and node.active('temp')[0].msg_type is Float64
    assert node.active('temp')[0].messages[-1].data == 26.
    assert row['output_info']['x']['temperature']['message_type'] == 'std_msgs/msg/Float64'
    assert len(node.active(row['topic'] + '/temperature')) == 1


def test_explicit_component_mapping_keeps_compound_imu(catalogue):
    profile = copy.deepcopy(catalogue['LSM6DS'])
    profile['ros'] = {'version': 1, 'attributes': {'gx': {'message_type': 'std_msgs/msg/Float64'}}}
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10), custom_messages=False)
    payload = (bytes([6, 0, 0, 0]) + struct.pack('<6h', 100, 0, 0, 0, 0, 8192))
    _, row = publish_profile(adapter, profile, payload.ljust(profile['resp']['b'], b'\0'))
    root = row['topic']
    assert node.active(root + '/data_raw')
    assert node.active(root + '/gx')[0].messages[-1].data == (
        node.active(root + '/data_raw')[0].messages[-1].angular_velocity.x)
    assert not node.active(root + '/ax') and not node.warnings


def test_array_mapping_does_not_replace_thermal_images(grid_profiles):
    profile = copy.deepcopy(grid_profiles['AMG8833'])
    profile['ros'] = {'version': 1, 'attributes': {
        'temperature': {'message_type': 'sensor_msgs/msg/Temperature'}}}
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10))
    _, row = publish_profile(adapter, profile, struct.pack('<64h', *([100] * 64)))
    assert set(row['public_topics']['x']) == {'sample', 'data', 'grid', 'image'}
    assert len(node.warnings) == 1


def test_invalid_mapped_bool_and_text_omit_readings_without_changing_type():
    profile = mapped_profile([
        {'n': 'ready', 't': 'B', 'o': 'bool', 'vft': 'valid'},
        {'n': 'label', 't': '4s', 'vft': 'valid'},
        {'n': 'tempC', 't': 'h', 'u': '&deg;C', 'vft': 'valid'},
        {'n': 'valid', 't': 'B', 'o': 'bool'},
    ], {'ready': 'std_msgs/msg/Bool', 'label': 'std_msgs/msg/String',
        'tempC': 'sensor_msgs/msg/Temperature'})
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10))
    for valid in (0, 1, 0):
        _, row = publish_profile(adapter, profile, struct.pack('=B4shB', 1, b'abc\0', 25, valid))
    root = row['topic']
    assert [m.data for m in node.active(root + '/ready')[0].messages] == [True]
    assert [m.data for m in node.active(root + '/label')[0].messages] == ['abc']
    messages = node.active(root + '/tempC')[0].messages
    assert math.isnan(messages[0].temperature) and messages[1].temperature == 25.
    assert math.isnan(messages[2].temperature) and not node.warnings


def test_declared_attributes_in_separate_payload_groups_publish_independently():
    profile = mapped_profile([
        {'n': 'photodiode', 't': '<H', 'u': 'lux'},
        {'n': 'tempC', 't': '<h', 'u': '&deg;C'},
    ], {'photodiode': 'sensor_msgs/msg/Illuminance', 'tempC': 'sensor_msgs/msg/Temperature'})
    payload = struct.pack('<Hh', 100, 25)
    node = RecordingNode()
    adapter = RosAdapters(node, QoSProfile(depth=10), topic_aliases={
        'light': {'type': 'LibrarySensor', 'source': 'photodiode'}})
    device, _ = publish_profile(adapter, profile, payload)
    values = SampleDecoder().values(payload, profile['resp'])[0][0]
    for group, name in (('light', 'photodiode'), ('thermal', 'tempC')):
        measurement = sample()
        measurement['values'] = {name: values[name]}
        adapter.publish(device, group, measurement)
    rows = inventory(device)
    adapter.sync(rows)
    assert set(rows[0]['public_topics']['light']) == {'sample', 'data', 'photodiode'}
    assert set(rows[0]['public_topics']['thermal']) == {'sample', 'data', 'tempC'}
    assert len(node.active('light')[0].messages) == 1
    assert not node.warnings
