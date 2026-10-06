"""Exercise the teaching controls with real child ROS processes and MCAP playback."""

import json
import socket
import threading
import time
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest

rclpy = pytest.importorskip('rclpy')
from axiom_shake_detector.presentation import TeachingNode  # noqa: E402,I100
from rclpy.executors import SingleThreadedExecutor  # noqa: E402


def wait_for(condition, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return
        time.sleep(0.04)
    assert condition(), 'Teaching flow did not reach the expected state'


def test_face_is_independent_and_replay_uses_actual_ros_events(tmp_path):
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    rclpy.init(
        args=[
            '--ros-args',
            '-p',
            'with_driver:=false',
            '-p',
            f'dashboard_port:={port}',
            '-p',
            f'recordings_dir:={tmp_path}',
        ]
    )
    node = TeachingNode()
    executor = SingleThreadedExecutor()
    executor.add_node(node)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()
    url = f'http://127.0.0.1:{port}'

    def action(action_name, **values):
        request = Request(
            url + '/api/action',
            json.dumps({'action': action_name, **values}).encode(),
            {'Content-Type': 'application/json', 'X-Axiom-Lab': 'teaching'},
        )
        with urlopen(request, timeout=3) as response:
            assert response.status == 202
        wait_for(lambda: not node.experiments.busy)
        assert not node.experiments.error, node.experiments.error

    try:
        wait_for(lambda: 'shake_detector' in node.snapshot()['graph']['nodes'])
        assert not node.experiments.running('face')
        action('face_on')
        action('strict_on')
        wait_for(
            lambda: (
                node.snapshot()['face_alive']
                and 'strict_detector' in node.snapshot()['graph']['nodes']
            )
        )
        action('sample', rate=2)
        wait_for(lambda: not node.experiments.running('player'))
        wait_for(lambda: node.snapshot()['face']['reactions'] == 2)
        state = node.snapshot()
        assert state['samples'] == 600 and state['count'] == 2
        assert state['strict_count'] == 0
        assert state['face']['expression'] == 'surprised'
        assert state['experiment']['source'] == 'synthetic'
        assert len(state['graph']['imu_subscribers']) == 3
        assert len(state['graph']['event_subscribers']) == 2
        stamps = [e['stamp'] for e in state['events']]
        assert stamps == [101.27, 104.27]
        bag = state['experiment']['bag']
        action('replay', name=bag, rate=1)
        wait_for(lambda: not node.experiments.running('player'))
        wait_for(lambda: node.snapshot()['face']['reactions'] == 2)
        assert [e['stamp'] for e in node.snapshot()['events']] == stamps
        assert node.snapshot()['samples'] == 600
        detector_pid = node.experiments.processes['detector'].pid
        action('face_off')
        wait_for(lambda: 'robot_face' not in node.snapshot()['graph']['nodes'])
        assert node.experiments.processes['detector'].pid == detector_pid
        assert node.experiments.running('detector')
        assert node.snapshot()['count'] == 2
        with pytest.raises(ValueError, match='Select a recording'):
            node.experiments.select_bag('../outside')
        with pytest.raises(ValueError, match='Connect live'):
            node.experiments.record(15)
        bad = Request(
            url + '/api/action',
            b'{"action":"live"}',
            {
                'Content-Type': 'application/json',
                'X-Axiom-Lab': 'teaching',
                'Origin': 'https://unrelated.example',
            },
        )
        with pytest.raises(HTTPError) as error:
            urlopen(bad, timeout=3)
        assert error.value.code == 403
    finally:
        executor.shutdown()
        thread.join(timeout=3)
        node.destroy_node()
        rclpy.shutdown()
