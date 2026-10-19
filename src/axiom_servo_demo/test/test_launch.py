"""Exercise the installed launch, real joint slider GUI and target-preview TF."""

import math
import os
from pathlib import Path
import signal
import subprocess
import time
import xml.etree.ElementTree as ET

import pytest

rclpy = pytest.importorskip('rclpy')
from rclpy.node import Node  # noqa: E402,I100
from rclpy.qos import DurabilityPolicy, QoSProfile  # noqa: E402
from sensor_msgs.msg import JointState  # noqa: E402
from std_msgs.msg import String  # noqa: E402
from tf2_msgs.msg import TFMessage  # noqa: E402


def test_installed_launch_starts_slider_and_preview_with_matching_limits(tmp_path):
    """Run the unchanged joint GUI offscreen and verify its actual ROS output."""
    rclpy.init()
    probe = Node('servo_launch_probe', use_global_arguments=False)
    commands, descriptions, transforms = [], [], []
    probe.create_subscription(JointState, '/servo_demo/joint_commands', commands.append, 10)
    retained = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
    probe.create_subscription(
        String, '/servo_demo/robot_description', descriptions.append, retained)
    probe.create_subscription(TFMessage, '/tf', transforms.append, 10)
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', XDG_RUNTIME_DIR=str(tmp_path / 'runtime'))
    Path(env['XDG_RUNTIME_DIR']).mkdir(mode=0o700)
    command = [
        'ros2', 'launch', 'axiom_servo_demo', 'servo_demo.launch.py',
        'axiom_namespace:=/unused_servo_demo_board', 'rviz:=false',
        'lower_limit_deg:=20.0', 'upper_limit_deg:=40.0',
    ]
    log_path = tmp_path / 'servo-launch.log'
    with log_path.open('w') as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=log, env=env, start_new_session=True)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                rclpy.spin_once(probe, timeout_sec=0.05)
                assert process.poll() is None, log_path.read_text()
                if commands and descriptions and transforms:
                    break
            assert commands and descriptions and transforms, log_path.read_text()
            assert commands[-1].name == ['servo_joint']
            assert commands[-1].position[0] == pytest.approx(math.radians(30), abs=0.001)
            robot = ET.fromstring(descriptions[-1].data)
            limit = robot.find("joint[@name='servo_joint']/limit")
            assert float(limit.get('lower')) == pytest.approx(math.radians(20))
            assert float(limit.get('upper')) == pytest.approx(math.radians(40))
            horn = next(t for msg in transforms for t in msg.transforms
                        if t.child_frame_id == 'servo_horn')
            assert horn.header.frame_id == 'axiom_servo_demo_base'
            assert horn.transform.rotation.z == pytest.approx(
                math.sin(math.radians(15)), abs=0.001)
            nodes = probe.get_node_names_and_namespaces()
            assert ('servo_adapter', '/servo_demo') in nodes
            assert not any(name == 'axiom_bridge_node' for name, _ in nodes)
            process.send_signal(signal.SIGINT)
            assert process.wait(timeout=10) == 0, log_path.read_text()
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
            probe.destroy_node()
            rclpy.shutdown()
