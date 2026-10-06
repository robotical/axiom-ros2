"""Real DDS IMU input, typed shake output and browser state."""

import json
import math
import socket
import time
from urllib.request import urlopen

import pytest

rclpy = pytest.importorskip('rclpy')
from axiom_interfaces.msg import ShakeEvent  # noqa: E402,I100 (optional ROS imports)
from axiom_shake_detector.node import ShakeNode  # noqa: E402
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.qos import qos_profile_sensor_data  # noqa: E402
from sensor_msgs.msg import Imu  # noqa: E402


def test_ros_motion_to_event_and_http_dashboard():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        port = listener.getsockname()[1]
    rclpy.init(
        args=['--ros-args', '-p', 'imu_topic:=/shake_test/imu', '-p', f'dashboard_port:={port}']
    )
    detector = ShakeNode()
    probe = Node('shake_test_probe', use_global_arguments=False)
    executor = SingleThreadedExecutor()
    executor.add_node(detector)
    executor.add_node(probe)
    publisher = probe.create_publisher(Imu, '/shake_test/imu', qos_profile_sensor_data)
    events = []
    subscription = probe.create_subscription(ShakeEvent, '/shake/events', events.append, 10)
    try:
        deadline = time.monotonic() + 5
        while publisher.get_subscription_count() == 0 and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.01)
        assert publisher.get_subscription_count() == 1
        assert subscription is not None
        for i in range(400):
            t = i / 100
            msg = Imu()
            msg.header.stamp.sec = 10 + i // 100
            msg.header.stamp.nanosec = (i % 100) * 10_000_000
            msg.header.frame_id = 'test_imu'
            msg.linear_acceleration.z = 9.81
            if 1 < t < 3:
                msg.linear_acceleration.x = 7 * math.sin(2 * math.pi * 4 * t)
            publisher.publish(msg)
            # Wait for each measurement; avoid making DDS packet loss part of this test.
            deadline = time.monotonic() + 1
            while detector.sample_count <= i and time.monotonic() < deadline:
                executor.spin_once(timeout_sec=0.001)
            assert detector.sample_count == i + 1
        deadline = time.monotonic() + 2
        while not events and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.01)
        assert events and events[0].pulse_count == 3
        assert events[0].header.frame_id == 'test_imu'
        assert events[0].motion_m_s2 >= 3
        with urlopen(f'http://127.0.0.1:{port}/api/state', timeout=2) as response:
            state = json.load(response)
        assert state['count'] == detector.event_count and state['count'] >= 1
        assert state['samples'] == 400 and state['connected']
        with urlopen(f'http://127.0.0.1:{port}', timeout=2) as response:
            assert b'Movement lab' in response.read()
    finally:
        executor.shutdown()
        detector.destroy_node()
        probe.destroy_node()
        rclpy.shutdown()
