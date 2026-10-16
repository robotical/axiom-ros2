"""Automatic startup against real serial, HTTP, WebSocket, mDNS and DDS peers."""

import socket
import threading
from types import SimpleNamespace
from unittest.mock import Mock
import uuid

import pytest

rclpy = pytest.importorskip('rclpy')
from axiom_driver.discovery_node import AxiomDiscoveryNode  # noqa: E402,I100
from axiom_interfaces.srv import Disconnect  # noqa: E402
from rclpy.context import Context  # noqa: E402
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402
from rclpy.qos import qos_profile_sensor_data  # noqa: E402
from sensor_msgs.msg import Range  # noqa: E402
from test_ros_integration import wait_until  # noqa: E402
from test_serial_integration import SerialFirmware  # noqa: E402
from test_session import FirmwareServer  # noqa: E402
from zeroconf import IPVersion, ServiceInfo, Zeroconf  # noqa: E402

ID_A, ID_B = '001122334455', 'aabbccddeeff'


def version(identity):
    return {'SystemName': 'Axiom018', 'MAC': identity}


@pytest.fixture
def running_discovery(tmp_path):
    context = Context()
    rclpy.init(args=[], context=context)
    executor = SingleThreadedExecutor(context=context)
    nodes, threads, errors = [], [], []
    # Never acquire physical LAN boards while running synthetic peer tests.
    config = tmp_path / 'selected-test-boards.yaml'
    config.write_text(
        'discovery:\n  include_unconfigured: false\naxioms:\n'
        + ''.join(f'  axiom_{identity}:\n    id: "{identity}"\n'
                  for identity in (ID_A, ID_B)))

    def start(ports, network=None):
        node = AxiomDiscoveryNode(
            port_provider=ports, network_provider=network, context=context,
            use_global_arguments=False,
            parameter_overrides=[Parameter('boards_file', value=str(config))],
        )
        nodes.append(node)
        node._timer.timer_period_ns = 20_000_000
        node._timer.reset()
        executor.add_node(node)
        probe = Node('auto_startup_probe', context=context, use_global_arguments=False)
        nodes.append(probe)
        executor.add_node(probe)

        def spin():
            try:
                executor.spin()
            except Exception as exc:
                errors.append(exc)

        thread = threading.Thread(target=spin, daemon=True)
        threads.append(thread)
        thread.start()
        return SimpleNamespace(node=node, probe=probe, executor=executor)

    try:
        yield start
    finally:
        executor.shutdown(timeout_sec=5)
        for thread in threads:
            thread.join(5)
        for node in nodes:
            node.destroy_node()
        context.shutdown()
        assert not errors


def test_real_mdns_discovers_two_boards_and_keeps_topics_frames_and_lifetimes_isolated(
    running_discovery, catalogue,
):
    peers = [FirmwareServer(firmware=version(identity)) for identity in (ID_A, ID_B)]
    zc = Zeroconf(ip_version=IPVersion.V4Only)
    services = []
    env = running_discovery(lambda: [])
    ranges = [[], []]
    for index, (identity, peer) in enumerate(zip((ID_A, ID_B), peers)):
        def reply(path, response):
            if isinstance(path, str) and path.startswith('devman/typeinfo'):
                response.update(dtIdx=1, devinfo=catalogue['VL53L4CD'])
            return response
        peer.callback = reply
        info = ServiceInfo(
            '_http._tcp.local.', f'Axiom-{uuid.uuid4().hex}._http._tcp.local.',
            addresses=[socket.inet_aton('127.0.0.1')], port=peer.port,
            properties={b'board': b'esp32', b'path': b'/'},
        )
        services.append(info)
        env.probe.create_subscription(
            Range, f'/axiom_{identity}/bus_1/device_29/range', ranges[index].append,
            qos_profile_sensor_data,
        )
    registered = []
    try:
        for info in services:
            zc.register_service(info)
            registered.append(info)
        wait_until(lambda: set(env.node._drivers) == {ID_A, ID_B}
                   and all(driver._subscribed for _, driver in env.node._drivers.values()),
                   timeout=12)
        first = env.node._drivers[ID_A][1]
        second = env.node._drivers[ID_B][1]
        assert all(len(peer.connections) == 1 for peer in peers)

        def publish():
            for peer, distance in zip(peers, ('0064', '012c')):
                peer.publish({'_v': 1, '1': {'29': {
                    '_i': 1, '_o': 1, 'x': '006400' + distance,
                }}})

        publish()
        wait_until(lambda: all(env.probe.count_publishers(
            f'/axiom_{identity}/bus_1/device_29/range') == 1 for identity in (ID_A, ID_B)))
        # Re-publish until DDS discovery has delivered both publishers' measurements.
        for _ in range(3):
            publish()
            if all(ranges):
                break
            threading.Event().wait(0.1)
        wait_until(lambda: all(ranges))
        assert ranges[0][-1].range == pytest.approx(0.1)
        assert ranges[1][-1].range == pytest.approx(0.3)
        assert ranges[0][-1].header.frame_id != ranges[1][-1].header.frame_id

        # An explicit user disconnect must survive discovery scans and reappearance.
        client = env.probe.create_client(Disconnect, f'/axiom_{ID_A}/disconnect')
        assert client.wait_for_service(timeout_sec=3)
        response = client.call_async(Disconnect.Request())
        wait_until(response.done)
        assert response.result().success
        zc.unregister_service(services[0])
        registered.remove(services[0])
        wait_until(lambda: ID_A not in env.node._drivers, timeout=8)
        assert env.node._drivers[ID_B][1] is second and second.session.connected
        zc.register_service(services[0])
        registered.append(services[0])
        wait_until(lambda: ID_A in env.node._drivers, timeout=8)
        replacement = env.node._drivers[ID_A][1]
        assert replacement is not first and not replacement._desired_connection
        assert not replacement.session.connected
        assert env.node._drivers[ID_B][1] is second and second._subscribed
    finally:
        for info in registered:
            zc.unregister_service(info)
        zc.close()
        for peer in peers:
            peer.close()


def test_live_wifi_to_usb_handover_and_fallback_have_one_acquisition_owner(running_discovery):
    wifi = FirmwareServer(firmware=version(ID_A))
    usb = SerialFirmware(version_response=version(ID_A))
    ports = Mock(return_value=[])
    network = Mock(spec=['snapshot', 'close'])
    network.snapshot.return_value = [wifi.uri]
    env = running_discovery(ports, network)
    try:
        wait_until(lambda: ID_A in env.node._drivers and env.node._drivers[ID_A][1]._subscribed)
        first = env.node._drivers[ID_A][1]
        assert first.config['transport'] == 'ws' and len(wifi.connections) == 1
        ports.return_value = [SimpleNamespace(device=usb.path, vid=0x303A, pid=0x1001)]
        wait_until(lambda: ID_A in env.node._drivers
                   and env.node._drivers[ID_A][0][0] == 'serial'
                   and env.node._drivers[ID_A][1]._subscribed, timeout=8)
        serial_driver = env.node._drivers[ID_A][1]
        wait_until(lambda: not wifi.connections)
        assert serial_driver is not first
        assert serial_driver.get_namespace() == '/axiom_' + ID_A
        assert serial_driver.session.connected
        assert usb.commands[0] == usb.commands[1] == 'v'
        assert len(env.node._drivers) == 1

        ports.return_value = []
        wait_until(lambda: ID_A in env.node._drivers
                   and env.node._drivers[ID_A][0][0] == 'ws'
                   and env.node._drivers[ID_A][1]._subscribed, timeout=8)
        assert not serial_driver.session.connected and not serial_driver._worker.is_alive()
        assert len(wifi.connections) == 1 and len(env.node._drivers) == 1
    finally:
        # Stop the driver before its peer, keeping cleanup independent of retries.
        env.executor.shutdown(timeout_sec=5)
        for identity in list(env.node._drivers):
            env.node._stop_driver(identity)
        usb.close()
        wifi.close()
