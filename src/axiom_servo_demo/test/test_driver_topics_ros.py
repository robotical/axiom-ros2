"""Joint-slider input through the actual topic driver to mock firmware."""

import json
import math
from pathlib import Path
import sys
import time

import pytest

rclpy = pytest.importorskip('rclpy')
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'axiom_driver/test'))
from axiom_servo_demo.node import ServoAdapter  # noqa: E402,I100
from rclpy.parameter import Parameter  # noqa: E402
from sensor_msgs.msg import JointState  # noqa: E402
from std_srvs.srv import SetBool  # noqa: E402
from test_output_topics_ros import OutputRig  # noqa: E402
from test_ros_integration import wait_until  # noqa: E402


def test_slider_auto_enable_topic_dispatch_and_disable_reach_firmware():
    """Use the driver's actual inventory and services with no angle-service shim."""
    path = (Path(__file__).resolve().parents[2]
            / 'axiom_driver/test/fixtures/firmware_catalogue.json')
    rig = OutputRig(json.loads(path.read_text())['records'], namespace='/servo_e2e_board')
    adapter = ServoAdapter(
        namespace='/servo_e2e_demo', use_global_arguments=False,
        parameter_overrides=[Parameter('axiom_namespace', value='/servo_e2e_board')])
    rig.executor.add_node(adapter)
    slider = rig.probe.create_publisher(JointState, '/servo_e2e_demo/joint_commands', 1)
    position = [0.05]
    rig.probe.create_timer(0.05, lambda: slider.publish(JointState(
        name=['servo_joint', 'leg_right_thigh_back_joint', 'leg_right_knee_upper_joint'],
        position=[position[0], position[0], -position[0]])))
    try:
        rig.connect()
        wait_until(lambda: adapter.gate.armed)
        assert [item['hexWr'][0] for item in rig.writes()] == ['2001']
        position[0] = math.radians(12.34)
        wait_until(lambda: len(rig.writes()) == 2)
        assert rig.writes()[-1]['hexWr'] == ['0001007b0064']
        client = rig.probe.create_client(SetBool, '/servo_e2e_demo/set_enabled')
        assert client.wait_for_service(timeout_sec=3)
        disable = client.call_async(SetBool.Request(data=False))
        wait_until(disable.done)
        assert disable.result().success
        position[0] = 0.3
        time.sleep(.2)
        assert [item['hexWr'][0] for item in rig.writes()] == [
            '2001', '0001007b0064', '2000']
    finally:
        rig.close(extra_nodes=[adapter])
