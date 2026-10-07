"""The guide uses local board settings before any driver has been started."""

import json
import shlex
from urllib.request import urlopen

import pytest

rclpy = pytest.importorskip('rclpy')
from axiom_marty_dashboard.node import Dashboard  # noqa: E402


def test_offline_guide_and_commands_share_machine_board_file(tmp_path, monkeypatch):
    path = tmp_path / 'board settings.yaml'
    path.write_text(json.dumps({'axioms': {
        'axiom/usb': {'transport': 'serial', 'serial.port': '/dev/serial/by-id/usb-Axiom'},
        'axiom/wifi': {'transport': 'ws', 'device_uri': 'ws://192.168.1.3/ws'},
    }}))
    monkeypatch.setenv('AXIOM_ROS_BOARDS_FILE', str(path))
    monkeypatch.setenv('AXIOM_DASHBOARD_PORT', '0')
    rclpy.init()
    observer = Dashboard()
    try:
        url = f'http://127.0.0.1:{observer.panel.server.server_port}/api/state'
        with urlopen(url, timeout=2) as response:
            state = json.load(response)
        assert set(state['guides']) == {'/axiom/usb', '/axiom/wifi'}
        assert all(b['state'] == 'driver offline' for b in state['boards'])
        for namespace, guide in state['guides'].items():
            command = next(c['command'] for c in guide['commands'] if c['title'] == 'Axiom driver')
            tokens = shlex.split(command)
            assert 'namespace:=' + namespace in tokens
            assert 'boards_file:=' + str(path) in tokens
            assert 'auto_connect:=false' in tokens and 'autosub:=false' in tokens
            assert 'serial.port:=' not in command and 'device_uri:=' not in command
    finally:
        observer.close()
        observer.destroy_node()
        rclpy.shutdown()
