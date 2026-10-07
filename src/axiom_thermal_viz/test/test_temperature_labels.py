"""Check live label updates and retirement over DDS."""

import time

from axiom_interfaces.msg import ThermalGrid
from axiom_thermal_viz.thermal_viz_node import ThermalGridVisualizer
import pytest
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.parameter import Parameter
from visualization_msgs.msg import Marker, MarkerArray


@pytest.fixture
def receive_labels():
    rclpy.init()
    viewer = ThermalGridVisualizer()
    sink = rclpy.create_node('thermal_labels_test')
    received = []
    sink.create_subscription(MarkerArray, '/thermal_heatmap_labels', received.append, 10)
    executor = SingleThreadedExecutor()
    executor.add_node(viewer)
    executor.add_node(sink)

    def receive(width, height, temperatures):
        deadline = time.monotonic() + 5
        while not viewer._label_publisher.get_subscription_count():
            assert time.monotonic() < deadline, 'Label subscriber was not discovered'
            executor.spin_once(timeout_sec=0.05)
        msg = ThermalGrid()
        msg.header.frame_id = 'camera_frame'
        msg.width, msg.height = width, height
        msg.temperature_c = temperatures
        before = len(received)
        viewer._handle_grid(msg)
        while len(received) == before:
            assert time.monotonic() < deadline, 'Labels were not received'
            executor.spin_once(timeout_sec=0.05)
        return received[-1].markers

    try:
        yield viewer, receive
    finally:
        executor.shutdown()
        sink.destroy_node()
        viewer.destroy_node()
        rclpy.shutdown()


def test_readings_and_removed_pixels_are_updated(receive_labels):
    _, receive = receive_labels
    labels = receive(2, 2, [20.0, 21.25, 22.5, 23.0])
    assert [label.text for label in labels] == ['20.0°', '21.2°', '22.5°', '23.0°']
    assert all(label.header.frame_id == 'camera_frame' for label in labels)
    assert all(label.type == Marker.TEXT_VIEW_FACING for label in labels)
    # Row zero starts at the top left. Each label stays in its pixel's top-right quarter.
    assert -0.01 < labels[0].pose.position.x < 0.0
    assert 0.01 < labels[0].pose.position.y < 0.02
    assert labels[0].pose.position.z > 0.0005
    labels = receive(2, 1, [24.0, 25.0])
    assert [(label.id, label.action) for label in labels] == [
        (0, Marker.ADD), (1, Marker.ADD), (2, Marker.DELETE), (3, Marker.DELETE)]
    assert [label.text for label in labels[:2]] == ['24.0°', '25.0°']


def test_turning_labels_off_removes_existing_text(receive_labels):
    viewer, receive = receive_labels
    receive(2, 1, [20.0, 22.0])
    viewer.set_parameters([Parameter('show_temperatures', value=False)])
    labels = receive(2, 1, [21.0, 23.0])
    assert len(labels) == 2
    assert all(label.action == Marker.DELETE for label in labels)


def test_smoothing_keeps_labels_on_measured_pixels(receive_labels):
    viewer, receive = receive_labels
    viewer.set_parameters([Parameter('interpolation_factor', value=3)])
    labels = receive(2, 2, [20.0, 21.0, 22.0, 23.0])
    assert len(labels) == 4
    assert [label.text for label in labels] == ['20.0°', '21.0°', '22.0°', '23.0°']
    assert labels[1].pose.position.x - labels[0].pose.position.x == pytest.approx(0.02)
