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
from ament_index_python.packages import get_package_share_directory  # noqa: E402,I100
from rclpy.node import Node  # noqa: E402,I100
from rclpy.qos import DurabilityPolicy, QoSProfile  # noqa: E402
from sensor_msgs.msg import JointState  # noqa: E402
from std_msgs.msg import String  # noqa: E402
from tf2_msgs.msg import TFMessage  # noqa: E402


@pytest.mark.parametrize('model', ['servo', 'right_leg'])
def test_installed_launch_starts_slider_and_preview_with_matching_limits(tmp_path, model):
    """Check both installed models with the real GUI, including the hip linkage."""
    rclpy.init()
    probe = Node('servo_launch_probe', use_global_arguments=False)
    commands, descriptions, transforms, fixed = [], [], [], []
    probe.create_subscription(JointState, '/servo_demo/joint_commands', commands.append, 10)
    retained = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
    probe.create_subscription(
        String, '/servo_demo/robot_description', descriptions.append, retained)
    probe.create_subscription(TFMessage, '/tf', transforms.append, 10)
    probe.create_subscription(TFMessage, '/tf_static', fixed.append, retained)
    env = dict(os.environ, QT_QPA_PLATFORM='offscreen', XDG_RUNTIME_DIR=str(tmp_path / 'runtime'))
    Path(env['XDG_RUNTIME_DIR']).mkdir(mode=0o700)
    command = [
        'ros2', 'launch', 'axiom_servo_demo', 'servo_demo.launch.py',
        'axiom_namespace:=/unused_servo_demo_board', 'rviz:=false',
        'lower_limit_deg:=20.0', 'upper_limit_deg:=40.0',
    ]
    if model != 'servo':
        command.append('preview_model:=' + model)
    log_path = tmp_path / 'servo-launch.log'
    with log_path.open('w') as log:
        process = subprocess.Popen(
            command, stdout=log, stderr=log, env=env, start_new_session=True)
        try:
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                rclpy.spin_once(probe, timeout_sec=0.05)
                assert process.poll() is None, log_path.read_text()
                if commands and descriptions and transforms and (model == 'servo' or fixed):
                    break
            assert commands and descriptions and transforms, log_path.read_text()
            expected = {'servo_joint'}
            if model == 'right_leg':
                expected.update(['leg_right_thigh_back_joint', 'leg_right_knee_upper_joint'])
            assert set(commands[-1].name) == expected
            positions = dict(zip(commands[-1].name, commands[-1].position))
            assert positions['servo_joint'] == pytest.approx(math.radians(30), abs=0.001)
            robot = ET.fromstring(descriptions[-1].data)
            limit = robot.find("joint[@name='servo_joint']/limit")
            assert float(limit.get('lower')) == pytest.approx(math.radians(20))
            assert float(limit.get('upper')) == pytest.approx(math.radians(40))
            moving = {t.child_frame_id: t for msg in transforms for t in msg.transforms}
            if model == 'servo':
                horn = moving['servo_horn']
                assert horn.header.frame_id == 'axiom_servo_demo_base'
                assert horn.transform.rotation.z == pytest.approx(
                    math.sin(math.radians(15)), abs=0.001)
            else:
                assert fixed, log_path.read_text()
                assert positions['leg_right_thigh_back_joint'] == positions['servo_joint']
                assert positions['leg_right_knee_upper_joint'] == -positions['servo_joint']
                assert set(moving) == {
                    'leg_right_thigh_front', 'leg_right_thigh_back', 'leg_right_knee_upper'}
                for child, parent, direction in (
                        ('leg_right_thigh_front', 'hip_right', 1),
                        ('leg_right_thigh_back', 'hip_right', 1),
                        ('leg_right_knee_upper', 'leg_right_thigh_front', -1)):
                    transform = moving[child]
                    assert transform.header.frame_id == parent
                    assert transform.transform.rotation.y == pytest.approx(
                        direction * math.sin(math.radians(15)), abs=0.001)
                static = {t.child_frame_id: t for msg in fixed for t in msg.transforms}
                assert static['foot_right'].header.frame_id == 'leg_right_shin_interior'
                assert static['foot_right'].transform.rotation.w == pytest.approx(1)
                share = Path(get_package_share_directory('axiom_servo_demo'))
                for mesh in robot.findall('.//mesh'):
                    uri = mesh.get('filename')
                    assert uri.startswith('package://axiom_servo_demo/')
                    assert (share / uri.removeprefix('package://axiom_servo_demo/')).is_file()
                assert (share / 'meshes/marty_right_leg/LICENSE').is_file()
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
