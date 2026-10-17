"""Descriptor decoding through a firmware peer into real ROS scalar subscribers."""

import copy
import json
import threading
import time

import pytest

rclpy = pytest.importorskip('rclpy')
from axiom_driver.axiom_bridge_node import AxiomBridgeNode  # noqa: E402,I100
from rclpy.context import Context  # noqa: E402
from rclpy.executors import MultiThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402
from rclpy.qos import DurabilityPolicy, qos_profile_sensor_data, QoSProfile  # noqa: E402
from sensor_msgs.msg import Illuminance  # noqa: E402
from std_msgs.msg import Float64, String  # noqa: E402
from test_ros_integration import wait_until  # noqa: E402
from test_session import FirmwareServer  # noqa: E402


@pytest.mark.parametrize('mapping_mode', ['absent', 'mapped', 'invalid'])
def test_ltr390_standard_outputs_and_retained_inventory_over_dds(catalogue, mapping_mode):
    peer = FirmwareServer()
    profile = copy.deepcopy(catalogue['LTR-390'])
    light_name = 'photodiode' if mapping_mode == 'mapped' else 'ambient'
    profile['resp']['a'][0]['n'] = light_name
    if mapping_mode == 'mapped':
        profile['ros'] = {'version': 1, 'attributes': {
            light_name: {'message_type': 'sensor_msgs/msg/Illuminance'},
            'UVI': {'message_type': 'std_msgs/msg/Float64'}}}
    elif mapping_mode == 'invalid':
        profile['ros'] = {'version': 99, 'attributes': {}}

    def reply(path, response):
        if isinstance(path, str) and path.startswith('devman/typeinfo'):
            response.update(dtIdx=1, devinfo=profile)
        return response

    peer.callback = reply
    context = Context()
    rclpy.init(context=context)
    executor = MultiThreadedExecutor(num_threads=4, context=context)
    bridge = AxiomBridgeNode(namespace='/scalar_test', context=context, use_global_arguments=False,
                             parameter_overrides=[
                                 Parameter('device_uri', value=peer.uri),
                                 Parameter('frame_id', value='scalar_test'),
                                 Parameter('auto_connect', value=True),
                                 Parameter('autosub', value=True),
                                 Parameter('auto_reconnect', value=False),
                                 Parameter('topic_aliases', value=json.dumps({
                                     'uv': {'type': 'LTR-390', 'source': 'UVI'}})),
                             ])
    probe = Node('scalar_probe', context=context, use_global_arguments=False)
    executor.add_node(bridge)
    executor.add_node(probe)
    light, uv, aliases, inventories = [], [], [], []
    subscriptions = [
        probe.create_subscription(Illuminance, '/scalar_test/ltr_2d390_b1_53/' + light_name,
                                  light.append, qos_profile_sensor_data),
        probe.create_subscription(Float64, '/scalar_test/ltr_2d390_b1_53/UVI',
                                  uv.append, qos_profile_sensor_data),
        probe.create_subscription(Float64, '/scalar_test/uv',
                                  aliases.append, qos_profile_sensor_data),
    ]
    spinning = threading.Thread(target=executor.spin, daemon=True)
    spinning.start()
    packet = {'_v': 1, '1': {'53': {'_i': 1, '_o': 1, 'x': '00647d00003000'}}}
    try:
        wait_until(lambda: bridge._subscribed)
        peer.publish(packet)
        wait_until(lambda: probe.count_publishers('/scalar_test/ltr_2d390_b1_53/UVI') == 1)
        time.sleep(.2)  # Let the new DDS publishers match subscribers.
        peer.publish(packet)
        wait_until(lambda: light and uv and aliases)
        assert light[-1].illuminance == 100. and light[-1].variance == 0.
        assert light[-1].header.frame_id == 'scalar_test_bus_1_device_53'
        assert light[-1].header.stamp.sec > 0
        assert uv[-1].data == aliases[-1].data == 2.
        # Join late: inventory is retained, not dependent on another sensor row.
        subscriptions.append(probe.create_subscription(
            String, '/scalar_test/devices', lambda msg: inventories.append(json.loads(msg.data)),
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)))
        wait_until(lambda: inventories and inventories[-1][0]['output_info'].get('x'))
        row = inventories[-1][0]
        assert row['public_topics']['x']['UVI'] == 'ltr_2d390_b1_53/UVI'
        assert row['output_info']['x'][light_name] == {
            'message_type': 'sensor_msgs/msg/Illuminance', 'unit': 'lux'}
        assert row['output_info']['x']['UVI'] == {
            'message_type': 'std_msgs/msg/Float64', 'unit': 'index'}
        if mapping_mode == 'mapped':
            assert next(iter(bridge.pipeline.registry.devices.values())).metadata['ros'] == (
                profile['ros'])
        peer.publish({'_v': 1, '1': {'53': {'_i': 1, '_o': 0, 'x': ''}}})
        wait_until(lambda: inventories and not inventories[-1][0]['online'])
        assert inventories[-1][0]['public_topics'] == {}
        assert inventories[-1][0]['output_info'] == {}
        wait_until(lambda: probe.count_publishers('/scalar_test/ltr_2d390_b1_53/UVI') == 0
                   and probe.count_publishers('/scalar_test/uv') == 0)
        assert not bridge.pipeline.counts['decode_errors']
    finally:
        executor.shutdown(timeout_sec=3)
        spinning.join(3)
        bridge.destroy_node()
        probe.destroy_node()
        context.shutdown()
        peer.close()
    assert len(subscriptions) == 4
