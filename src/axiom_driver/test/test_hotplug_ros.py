"""Real DDS lifecycle and descriptor services for two independent firmware peers."""

import json
import threading
import time

import pytest

rclpy = pytest.importorskip('rclpy')
from axiom_driver.axiom_bridge_node import AxiomBridgeNode  # noqa: E402,I100
from axiom_interfaces.srv import (  # noqa: E402
    Connect, DeviceCommand, Disconnect, PublishedDataSubscription,
)
from rclpy.executors import MultiThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402
from rclpy.qos import qos_profile_sensor_data  # noqa: E402
from sensor_msgs.msg import Range  # noqa: E402
from test_ros_integration import wait_until  # noqa: E402
from test_session import FirmwareServer  # noqa: E402


def test_two_boards_hotplug_aliases_and_output_services(catalogue):
    peers = [FirmwareServer(), FirmwareServer()]
    profiles = {1: 'VL53L4CD', 2: 'QwiicLEDStick'}
    indices = [1, 1]
    for index, peer in enumerate(peers):
        def reply(path, response, index=index):
            if isinstance(path, str) and path.startswith('devman/typeinfo'):
                response.update(dtIdx=indices[index], devinfo=catalogue[profiles[indices[index]]])
            return response
        peer.callback = reply
    rclpy.init()
    bridges = []
    for name, peer in zip(('front', 'rear'), peers):
        params = [Parameter('device_uri', value=peer.uri),
                  Parameter('frame_id', value='axiom_' + name),
                  Parameter('stale_after_s', value=1.0),
                  Parameter('topic_aliases', value=json.dumps({
                      'range': {'type': 'VL53L4CD', 'source': 'range'}}))]
        bridges.append(AxiomBridgeNode(namespace='/axiom/' + name, use_global_arguments=False,
                                       parameter_overrides=params))
    probe = Node('hotplug_probe', use_global_arguments=False)
    executor = MultiThreadedExecutor(num_threads=6)
    for node in [*bridges, probe]:
        executor.add_node(node)
    spinning = threading.Thread(target=executor.spin, daemon=True)
    spinning.start()
    samples = [[], []]
    for name, messages in zip(('front', 'rear'), samples):
        probe.create_subscription(Range, '/axiom/' + name + '/range', messages.append,
                                  qos_profile_sensor_data)

    def call(kind, path, expect=True, **fields):
        client = probe.create_client(kind, path)
        try:
            assert client.wait_for_service(timeout_sec=3)
            future = client.call_async(kind.Request(**fields))
            wait_until(future.done)
            result = future.result()
            assert result.success is expect, result.message
            return result
        finally:
            probe.destroy_client(client)

    def publish(index, online=1, data='0064000064', address='29'):
        peers[index].publish({'_v': 1, '1': {address: {
            '_i': indices[index], '_o': online, 'x': data}}})

    try:
        assert all(not peer.connections for peer in peers)
        for name in ('front', 'rear'):
            call(Connect, '/axiom/' + name + '/connect', device_uri='')
            call(PublishedDataSubscription, '/axiom/' + name + '/publish_data_subscription',
                 rate_hz=20.0)
        for index in range(2):
            publish(index)
        wait_until(lambda: all(probe.count_publishers('/axiom/' + n + '/range') == 1
                               for n in ('front', 'rear')))
        time.sleep(.2)
        publish(0)
        publish(1, data='006400012c')
        wait_until(lambda: all(samples) and abs(samples[1][-1].range - .3) < 1e-6)
        assert samples[0][-1].range == pytest.approx(.1)
        assert samples[1][-1].range == pytest.approx(.3)
        assert samples[0][-1].header.frame_id != samples[1][-1].header.frame_id

        # Offline, rather than deleted, must retire the publisher even though the
        # probe's subscriber keeps the topic name registered in DDS.
        publish(0, online=0, data='')
        wait_until(lambda: probe.count_publishers('/axiom/front/range') == 0)
        assert probe.count_publishers('/axiom/front/bus_1/device_29/range') == 0
        assert probe.count_publishers('/axiom/rear/range') == 1

        # Replace it at the same bus/address with a device that has no resp schema.
        indices[0] = 2
        publish(0, data='')
        brightness = '/axiom/front/bus_1/device_29/commands/brightness'
        wait_until(lambda: any(name == brightness for name, _ in
                               probe.get_service_names_and_types()))
        assert not probe.count_publishers('/axiom/front/bus_1/device_29/sample')
        call(DeviceCommand, brightness, values=[50.0])
        assert 'hexWr=7632' in peers[0].paths[-1]
        call(DeviceCommand, brightness.replace('brightness', 'pixels'),
             values=[0.0, 0.0, 16.0, 16.0])
        assert 'hexWr=7100001010' in peers[0].paths[-1]
        before = len(peers[0].paths)
        call(DeviceCommand, brightness, expect=False, values=[300.0])
        assert len(peers[0].paths) == before
        call(DeviceCommand, brightness.replace('brightness', 'off'), values=[])
        assert 'hexWr=78' in peers[0].paths[-1]
        publish(0, online=0, data='')
        wait_until(lambda: brightness not in dict(probe.get_service_names_and_types()))

        # Replugging restores the stable alias without restarting any node.
        indices[0] = 1
        publish(0)
        wait_until(lambda: probe.count_publishers('/axiom/front/range') == 1)
        # Two matching devices must remove the alias, while preserving both raw topics.
        publish(0, address='129')
        wait_until(lambda: probe.count_publishers('/axiom/front/range') == 0)
        assert probe.count_publishers('/axiom/front/bus_1/device_129/range') == 1
        assert probe.count_publishers('/axiom/front/bus_1/device_29/range') == 1
        publish(0, online=2, address='129', data='')
        publish(0)
        wait_until(lambda: probe.count_publishers('/axiom/front/range') == 1)
        # Silence expires interfaces; recovery from fresh packets recreates them.
        wait_until(lambda: probe.count_publishers('/axiom/front/range') == 0, timeout=3)
        publish(0)
        publish(1)
        wait_until(lambda: all(probe.count_publishers('/axiom/' + n + '/range') == 1
                               for n in ('front', 'rear')))
        call(Disconnect, '/axiom/front/disconnect')
        wait_until(lambda: probe.count_publishers('/axiom/front/range') == 0)
        assert bridges[1].session.connected and len(peers[1].connections) == 1
    finally:
        executor.shutdown(timeout_sec=3)
        spinning.join(3)
        for node in [*bridges, probe]:
            node.destroy_node()
        rclpy.shutdown()
        for peer in peers:
            peer.close()
