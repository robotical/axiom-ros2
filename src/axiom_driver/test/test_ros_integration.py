"""Real rclpy messages, DDS fan-out and services against virtual firmware peers."""

import json
import struct
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest

rclpy = pytest.importorskip('rclpy')
from axiom_driver.axiom_bridge_node import (  # noqa: E402,I100 (optional ROS imports)
    AxiomBridgeNode,
)
from axiom_driver.usb_discovery_node import UsbDiscoveryNode  # noqa: E402
from axiom_interfaces.msg import (  # noqa: E402 (ROS is optional for pure tests)
    DeviceSample,
    VL53L4CDReading,
)
from axiom_interfaces.srv import (  # noqa: E402 (ROS is optional for pure tests)
    Connect,
    Disconnect,
    GetConnectionState,
    PublishedDataSubscription,
    SetSampleRate,
)
from rclpy.context import Context  # noqa: E402 (ROS is optional for pure tests)
from rclpy.executors import (  # noqa: E402 (ROS is optional for pure tests)
    MultiThreadedExecutor,
    SingleThreadedExecutor,
)
from rclpy.node import Node  # noqa: E402 (ROS is optional for pure tests)
from rclpy.parameter import Parameter  # noqa: E402
from rclpy.qos import (  # noqa: E402 (ROS is optional for pure tests)
    DurabilityPolicy,
    qos_profile_sensor_data,
    QoSProfile,
)
from sensor_msgs.msg import Imu, Range  # noqa: E402 (ROS is optional for pure tests)
from std_msgs.msg import String  # noqa: E402 (ROS is optional for pure tests)
from test_serial_integration import SerialFirmware  # noqa: E402 (ROS is optional for pure tests)
from test_session import FirmwareServer  # noqa: E402 (ROS is optional for pure tests)


def wait_until(predicate, timeout=4):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    assert predicate(), 'Timed out waiting for ROS integration condition'


def test_discovery_hands_serial_port_to_driver_and_restarts_it_after_replug(monkeypatch):
    import serial

    identity = '001122334455'
    peer = SerialFirmware(version_response={'SystemName': 'Axiom018', 'MAC': identity})
    serial_open = serial.Serial
    opened = []

    def open_virtual_serial(path, *args, **kwargs):
        assert path == peer.path, 'This test must only open its virtual serial device'
        assert all(not connection.is_open for connection in opened), 'Serial owners overlapped'
        connection = serial_open(path, *args, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(serial, 'Serial', open_virtual_serial)
    candidate = SimpleNamespace(device=peer.path, vid=0x303A, pid=0x1001)
    provider = Mock(return_value=[candidate])
    context = Context()
    rclpy.init(args=[], context=context)
    executor = SingleThreadedExecutor(context=context)
    discovery = spinning = None
    driver = replacement = None
    try:
        discovery = UsbDiscoveryNode(
            port_provider=provider, context=context, use_global_arguments=False,
            parameter_overrides=[Parameter('boards_file', value='')],
        )
        assert not discovery._drivers
        # Accelerate only the scan timer; use the real probe, driver and callbacks.
        discovery._timer.timer_period_ns = 20_000_000

        executor.add_node(discovery)
        spinning = threading.Thread(target=executor.spin, daemon=True)
        spinning.start()
        wait_until(lambda: identity in discovery._drivers
                   and discovery._drivers[identity][1]._subscribed)
        driver = discovery._drivers[identity][1]
        assert driver.session.connected
        assert driver.context is context and driver in executor.get_nodes()
        assert driver.get_fully_qualified_name() == f'/axiom_{identity}/axiom_bridge_node'

        subscription = {
            'cmdName': 'subscription',
            'action': 'update',
            'pubRecs': [{'name': 'devjson', 'rateHz': 10.0, 'trigger': 'time'}],
        }
        # One version request verifies the board; the second belongs to the driver.
        assert list(peer.commands) == ['v', 'v', subscription]
        assert len(opened) == 2 and not opened[0].is_open and opened[1].is_open
        scans = provider.call_count
        wait_until(lambda: provider.call_count >= scans + 3)
        assert len(opened) == 2, 'Discovery must not reprobe a port owned by its driver'
        assert discovery._drivers[identity][1] is driver
        assert driver.session.firmware['SystemName'] == 'Axiom018'

        provider.return_value = []
        wait_until(lambda: not discovery._drivers and not driver._worker.is_alive())
        assert driver not in executor.get_nodes()
        assert not driver.session.connected and not driver._worker.is_alive()
        assert all(not connection.is_open for connection in opened)

        provider.return_value = [candidate]
        wait_until(lambda: identity in discovery._drivers
                   and discovery._drivers[identity][1]._subscribed)
        replacement = discovery._drivers[identity][1]
        assert replacement is not driver and replacement in executor.get_nodes()
        assert replacement.session.connected
        assert list(peer.commands) == ['v', 'v', subscription] * 2
        assert len(opened) == 4
        assert all(not connection.is_open for connection in opened[:-1])
        assert opened[-1].is_open
    finally:
        executor.shutdown(timeout_sec=3)
        if spinning is not None:
            spinning.join(3)
        if discovery is not None:
            discovery.destroy_node()
        context.shutdown()
        peer.close()

    assert all(not connection.is_open for connection in opened)
    assert not replacement._worker.is_alive()
    assert not replacement.session.connected


def test_manual_connection_acquisition_stop_and_reconnect(catalogue):
    peer = FirmwareServer()

    def reply(request, response):
        if isinstance(request, str) and request.startswith('devman/typeinfo'):
            response.update(devinfo=catalogue['VL53L4CD'], dtIdx=1)
        return response

    peer.callback = reply
    rclpy.init(args=['--ros-args', '-p', f'device_uri:={peer.uri}',
                     '-p', 'auto_connect:=false', '-p', 'auto_reconnect:=false',
                     '-p', 'autosub:=false'])
    bridge = AxiomBridgeNode()
    probe = Node('manual_probe', use_global_arguments=False)
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(bridge)
    executor.add_node(probe)
    spinning = threading.Thread(target=executor.spin, daemon=True)
    spinning.start()
    raw, ranges = [], []
    subscriptions = [
        probe.create_subscription(String, '/raw/devjson', raw.append, 10),
        probe.create_subscription(
            Range, '/bus_1/device_29/range', ranges.append, qos_profile_sensor_data
        ),
    ]

    def call(kind, name, **fields):
        client = probe.create_client(kind, name)
        try:
            assert client.wait_for_service(timeout_sec=2)
            future = client.call_async(kind.Request(**fields))
            wait_until(future.done)
            assert future.result().success, future.result().message
            return future.result()
        finally:
            probe.destroy_client(client)

    packet = {'_v': 1, '_t': 0, '1': {'29': {'_i': 1, '_o': 1, 'x': '0064000064'}}}
    try:
        time.sleep(0.4)
        assert not peer.connections and not bridge._desired_connection
        assert not bridge.config['autosub'] and not bridge.config['auto_reconnect']
        connected = call(Connect, '/connect', device_uri='')
        assert 'acquisition stopped' in connected.message
        assert peer.paths == ['v'] and not peer.commands
        # Residual/unsolicited firmware data must not become ROS measurements.
        peer.publish(packet)
        time.sleep(0.3)
        assert not raw and not ranges and not bridge.pipeline.registry.devices
        call(PublishedDataSubscription, '/publish_data_subscription', rate_hz=20.0)
        peer.publish(packet)
        wait_until(lambda: probe.count_publishers('/bus_1/device_29/range') == 1)
        time.sleep(0.2)
        peer.publish(packet)
        wait_until(lambda: raw and ranges)
        assert ranges[-1].range == pytest.approx(0.1)
        call(PublishedDataSubscription, '/publish_data_subscription', rate_hz=0.0)
        time.sleep(0.2)  # Allow earlier DDS messages to reach the probe.
        stopped_counts = len(raw), len(ranges)
        peer.publish(packet)
        time.sleep(0.3)
        assert (len(raw), len(ranges)) == stopped_counts
        assert not bridge._subscribed and bridge._data.empty()
        assert bridge.session.connected
        call(PublishedDataSubscription, '/publish_data_subscription', rate_hz=20.0)
        peer.disconnect_clients()
        wait_until(lambda: not bridge.session.connected)
        disconnected_generation = bridge.session.generation
        time.sleep(0.5)
        assert not peer.connections and bridge.session.generation == disconnected_generation
        old_commands = len(peer.commands)
        call(Connect, '/connect', device_uri='')
        assert len(peer.commands) == old_commands and not bridge._subscribed
        peer.publish(packet)
        time.sleep(0.3)
        assert (len(raw), len(ranges)) == stopped_counts
    finally:
        assert len(subscriptions) == 2
        executor.shutdown(timeout_sec=3)
        spinning.join(3)
        bridge.destroy_node()
        probe.destroy_node()
        rclpy.shutdown()
        peer.close()


@pytest.mark.parametrize('connection_cycle', range(3))
def test_live_ros_messages_services_and_two_subscribers(catalogue, connection_cycle):
    peer = FirmwareServer()
    profiles = {'0x29': ('VL53L4CD', 1), '0x6a': ('LSM6DS', 2), '0x21': ('RoboticalVCP', 3)}

    def reply(request, response):
        if isinstance(request, str) and request.startswith('devman/typeinfo'):
            address = parse_qs(urlsplit(request).query)['addr'][0]
            name, index = profiles[address]
            response.update(devinfo=catalogue[name], dtIdx=index)
        if isinstance(request, str) and request.startswith('devman/devconfig'):
            response.update(sampleRateHz=100, pollIntervalUs=125000, numSamples=8)
        return response

    peer.callback = reply
    rclpy.init(
        args=[
            '--ros-args',
            '-p',
            'auto_connect:=true',
            '-p',
            'autosub:=true',
            '-p',
            'auto_reconnect:=true',
            '-p',
            f'device_uri:={peer.uri}',
            '-p',
            'reconnect_interval:=0.1',
            '-p',
            'sensor_qos.overrides:=\'{"bus_1/device_29/range":'
            '{"reliability":"reliable","depth":3}}\'',
        ]
    )
    bridge = AxiomBridgeNode()
    probe = Node('alignment_probe', use_global_arguments=False)
    executor = MultiThreadedExecutor(num_threads=4)
    executor.add_node(bridge)
    executor.add_node(probe)
    spinning = threading.Thread(target=executor.spin, daemon=True)
    spinning.start()
    samples_a, samples_b, ranges, invalids, imus, inventories = [], [], [], [], [], []
    _subscriptions = [
        probe.create_subscription(
            DeviceSample, '/bus_1/device_29/sample', samples_a.append, qos_profile_sensor_data
        ),
        probe.create_subscription(
            DeviceSample, '/bus_1/device_29/sample', samples_b.append, qos_profile_sensor_data
        ),
        probe.create_subscription(
            Range, '/bus_1/device_29/range', ranges.append, qos_profile_sensor_data
        ),
        probe.create_subscription(
            VL53L4CDReading, '/bus_1/device_29/range/raw', invalids.append, qos_profile_sensor_data
        ),
        probe.create_subscription(
            Imu, '/bus_1/device_6a/imu/data_raw', imus.append, qos_profile_sensor_data
        ),
        probe.create_subscription(
            String,
            '/devices',
            lambda msg: inventories.append(json.loads(msg.data)),
            QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL),
        ),
    ]
    assert len(_subscriptions) == 6
    try:
        wait_until(lambda: bridge._subscribed)
        assert bridge.describe_parameter('sensor_qos.depth').read_only
        # Prime publisher discovery before asserting DDS sample delivery.
        peer.publish({'_v': 1, '_t': 0, '1': {'29': {'_i': 1, '_o': 1, 'x': '0064000064'}}})
        wait_until(lambda: probe.count_publishers('/bus_1/device_29/sample') == 1)
        time.sleep(0.2)
        peer.publish({'_v': 1, '_t': 0, '1': {'29': {'_i': 1, '_o': 1, 'x': '0065040064'}}})
        wait_until(lambda: any(not msg.valid for msg in invalids))
        wait_until(lambda: samples_a and samples_b)
        assert samples_a[-1].values_json == samples_b[-1].values_json
        assert samples_a[-1].device_time_us == 10100
        assert json.loads(samples_a[-1].values_json)['dist']['value'] is None
        assert invalids[-1].distance_mm == 100
        assert samples_a[-1].header.frame_id == 'axiom_bus_1_device_29'
        assert samples_a[-1].header.stamp.sec > 0

        imu = bytes([12, 0, 0, 0]) + struct.pack(
            '<12h', -16384, 0, 0, 0, 0, 8192, 16384, 0, 0, 0, 8192, 0
        )
        payload = (b'\0\x64' + imu.ljust(244, b'\0')).hex()
        peer.publish({'_v': 1, '_t': 0, '1': {'6a': {'_i': 2, '_o': 1, 'x': payload}}})
        wait_until(lambda: probe.count_publishers('/bus_1/device_6a/imu/data_raw') == 1)
        time.sleep(0.2)
        payload = (b'\x01\x90' + imu.ljust(244, b'\0')).hex()
        peer.publish({'_v': 1, '_t': 0, '1': {'6a': {'_i': 2, '_o': 1, 'x': payload}}})
        wait_until(lambda: len(imus) >= 2)
        assert imus[-2].angular_velocity.x == pytest.approx(-17.45329252)
        assert imus[-1].linear_acceleration.y == pytest.approx(9.80665)
        assert imus[-1].orientation_covariance[0] == -1
        assert imus[-1].header.stamp != imus[-2].header.stamp

        vcp = (
            b'\0\x64'
            + (bytes([1, 1, 0, 0]) + struct.pack('>4h', 1000, 2000, 3000, 4000)).ljust(132, b'\0')
        ).hex()
        peer.publish({'_v': 1, '_t': 0, '1': {'21': {'_i': 3, '_o': 1, 'x': vcp}}})
        wait_until(lambda: any(d['address'] == '21' for d in bridge._inventory))
        rate_client = probe.create_client(SetSampleRate, '/set_sample_rate')
        assert rate_client.wait_for_service(timeout_sec=2)
        future = rate_client.call_async(
            SetSampleRate.Request(bus='1', address='21', sample_rate_hz=100.0)
        )
        wait_until(future.done)
        assert future.result().success, future.result().message
        assert future.result().poll_interval_us == 125000

        # An unexpected peer close must reconnect and restore the acknowledged
        # subscription. The first packet in the new session must create a publisher.
        old_generation = bridge.session.generation
        old_commands = len(peer.commands)
        peer.disconnect_clients()
        wait_until(lambda: bridge.session.generation > old_generation)
        wait_until(lambda: bridge._subscribed and len(peer.commands) > old_commands)
        assert len(peer.connections) == 1
        peer.publish({'_v': 1, '_t': 0, '1': {'29': {'_i': 1, '_o': 1, 'x': '0064000064'}}})
        wait_until(lambda: any(d['address'] == '29' for d in bridge._inventory))
        wait_until(lambda: probe.count_publishers('/bus_1/device_29/range') == 1)
        info = probe.get_publishers_info_by_topic('/bus_1/device_29/range')[0]
        # Fast DDS discovery does not expose history depth (reports zero).
        publisher = bridge.adapters.cache.get('bus_1/device_29/range', Range)
        assert publisher.qos_profile.depth == 3
        assert info.qos_profile.reliability.name == 'RELIABLE'
        peer.publish({'_v': 1, '_t': 0, '1': {'29': {'_i': 1, '_o': 2, 'x': ''}}})
        wait_until(lambda: inventories and all(d['address'] != '29' for d in inventories[-1]))
        wait_until(lambda: probe.count_publishers('/bus_1/device_29/sample') == 0)
        disconnect = probe.create_client(Disconnect, '/disconnect')
        assert disconnect.wait_for_service(timeout_sec=2)
        future = disconnect.call_async(Disconnect.Request())
        wait_until(future.done)
        assert future.result().success
        state = probe.create_client(GetConnectionState, '/get_connection_state')
        assert state.wait_for_service(timeout_sec=2)
        future = state.call_async(GetConnectionState.Request())
        wait_until(future.done)
        assert not future.result().connected
        assert len(peer.connections) == 0
    finally:
        executor.shutdown(timeout_sec=3)
        spinning.join(3)
        bridge.destroy_node()
        probe.destroy_node()
        rclpy.shutdown()
        peer.close()
