"""The installed launch file starts isolated boards with manual defaults."""

import json
import os
import signal
import subprocess

import pytest

rclpy = pytest.importorskip('rclpy')
from axiom_interfaces.srv import Connect, GetConnectionState  # noqa: E402,I100
from rcl_interfaces.srv import GetParameters  # noqa: E402
from test_session import FirmwareServer  # noqa: E402


def test_installed_multi_board_launch(tmp_path):
    peers = [FirmwareServer(), FirmwareServer()]
    config = tmp_path / 'boards.yaml'
    config.write_text(json.dumps({'axioms': {
        'axiom/' + name: {'transport': 'ws', 'device_uri': peer.uri}
        for name, peer in zip(('front', 'rear'), peers)}}))
    log = (tmp_path / 'launch.log').open('w+')
    launch = subprocess.Popen([
        'ros2', 'launch', 'axiom_driver', 'multi_axiom.launch.py',
        'boards_file:=' + str(config)], stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True)
    rclpy.init()
    probe = rclpy.create_node('multi_launch_probe')

    def call(kind, path, **values):
        client = probe.create_client(kind, path)
        try:
            assert client.wait_for_service(timeout_sec=12), path
            future = client.call_async(kind.Request(**values))
            rclpy.spin_until_future_complete(probe, future, timeout_sec=5)
            assert future.done(), path
            return future.result()
        finally:
            probe.destroy_client(client)

    try:
        for name in ('front', 'rear'):
            root = '/axiom/' + name
            assert not call(GetConnectionState, root + '/get_connection_state').connected
            params = call(GetParameters, root + '/axiom_bridge_node/get_parameters',
                          names=['frame_id', 'auto_connect', 'auto_reconnect', 'autosub'])
            assert params.values[0].string_value == 'axiom_' + name
            assert not any(value.bool_value for value in params.values[1:])
        assert not any(peer.connections for peer in peers)
        assert call(Connect, '/axiom/front/connect', device_uri='').success
        assert not call(GetConnectionState, '/axiom/rear/get_connection_state').connected
        assert call(Connect, '/axiom/rear/connect', device_uri='').success
        assert all(peer.connections for peer in peers)
        assert all(not any('subscription' in str(path).lower() for path in peer.paths)
                   for peer in peers)
    finally:
        probe.destroy_node()
        rclpy.shutdown()
        os.killpg(launch.pid, signal.SIGINT)
        try:
            launch.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(launch.pid, signal.SIGKILL)
            launch.wait(timeout=3)
        log.seek(0)
        print(log.read())
        log.close()
        for peer in peers:
            peer.close()


def test_installed_single_board_uses_machine_config_and_cli_overrides(tmp_path):
    peer = FirmwareServer()
    config = tmp_path / 'board settings.yaml'
    config.write_text(json.dumps({'axioms': {'axiom/configured': {
        'transport': 'ws', 'device_uri': peer.uri,
        'auto_connect': True, 'autosub': True, 'publish_rate_hz': 20.0,
        'topic_aliases': {'imu/data_raw': {'type': 'LSM6DS', 'source': 'imu/data_raw'}},
    }}}))
    log = (tmp_path / 'single-launch.log').open('w+')
    env = {**os.environ, 'AXIOM_ROS_BOARDS_FILE': str(config)}
    launch = subprocess.Popen([
        'ros2', 'launch', 'axiom_driver', 'axiom_minimal_launch.py',
        'namespace:=axiom/configured', 'auto_connect:=false', 'autosub:=false',
        'publish_rate_hz:=17.0'], env=env, stdout=log, stderr=subprocess.STDOUT,
        start_new_session=True)
    rclpy.init()
    probe = rclpy.create_node('machine_launch_probe')
    client = probe.create_client(
        GetParameters, '/axiom/configured/axiom_bridge_node/get_parameters')
    try:
        assert client.wait_for_service(timeout_sec=12)
        future = client.call_async(GetParameters.Request(names=[
            'device_uri', 'frame_id', 'auto_connect', 'autosub',
            'publish_rate_hz', 'topic_aliases']))
        rclpy.spin_until_future_complete(probe, future, timeout_sec=5)
        assert future.done()
        values = future.result().values
        assert values[0].string_value == peer.uri
        assert values[1].string_value == 'axiom_configured'
        assert not values[2].bool_value and not values[3].bool_value
        assert values[4].double_value == 17.0
        assert json.loads(values[5].string_value)['imu/data_raw']['type'] == 'LSM6DS'
        assert not peer.connections
    finally:
        probe.destroy_node()
        rclpy.shutdown()
        os.killpg(launch.pid, signal.SIGINT)
        try:
            launch.wait(timeout=10)
        except subprocess.TimeoutExpired:
            os.killpg(launch.pid, signal.SIGKILL)
            launch.wait(timeout=3)
        log.seek(0)
        print(log.read())
        log.close()
        peer.close()
