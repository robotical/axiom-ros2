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
