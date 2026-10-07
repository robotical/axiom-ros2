"""Both DDS inputs render independently; unavailable gyro is never treated as acceleration."""

from collections import deque
import math
import threading
import time

import pytest

rclpy = pytest.importorskip("rclpy")
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402
from rclpy.qos import qos_profile_sensor_data  # noqa: E402
from sensor_msgs.msg import Imu  # noqa: E402
from visualization_msgs.msg import Marker, MarkerArray  # noqa: E402
from axiom_marty_demo.accelerometer_view import AccelerometerView  # noqa: E402


def wait(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Dual accelerometer condition did not become true")


@pytest.fixture(params=["axiom-marty", "two-axioms"])
def dual_stack(request):
    rclpy.init()
    topics = {"Axiom": "/axiom/bus_3/device_76a/imu/data_raw", "Marty": "/marty/imu/data_raw"}
    labels = {"Axiom": "Axiom", "Marty": "Marty"}
    parameters = [Parameter("axiom_topic", value=topics["Axiom"])]
    if request.param == "two-axioms":
        topics = {"Axiom": "/axiom/front/imu/data_raw", "Marty": "/axiom/rear/imu/data_raw"}
        labels = {"Axiom": "Axiom USB", "Marty": "Axiom Wi-Fi"}
        parameters = [
            Parameter("axiom_topic", value=topics["Axiom"]),
            Parameter("marty_topic", value=topics["Marty"]),
            Parameter("axiom_label", value=labels["Axiom"]),
            Parameter("marty_label", value=labels["Marty"]),
        ]
    view = AccelerometerView(
        namespace="dual_test",
        parameter_overrides=parameters,
    )
    source = Node("dual_source")
    publishers = {
        name: source.create_publisher(Imu, topic, qos_profile_sensor_data)
        for name, topic in topics.items()
    }
    settings = {
        name: dict(
            streaming=True, acceleration=(0.0, 0.0, sign * 9.80665), covariance=0.0, stamp=None
        )
        for name, sign in (("Axiom", -1), ("Marty", 1))
    }
    frames = deque(maxlen=5)
    source.create_subscription(
        MarkerArray,
        "/dual_test/visualization/accelerometers",
        lambda msg: frames.append(msg),
        qos_profile_sensor_data,
    )

    def publish():
        for name, publisher in publishers.items():
            data = settings[name]
            if not data["streaming"]:
                continue
            msg = Imu()
            msg.header.stamp = data["stamp"] or source.get_clock().now().to_msg()
            msg.orientation_covariance[0] = msg.angular_velocity_covariance[0] = -1.0
            msg.angular_velocity.x = float("nan")
            msg.linear_acceleration_covariance[0] = data["covariance"]
            msg.linear_acceleration.x, msg.linear_acceleration.y, msg.linear_acceleration.z = data[
                "acceleration"
            ]
            publisher.publish(msg)

    source.create_timer(0.1, publish)
    executor = SingleThreadedExecutor()
    executor.add_node(view)
    executor.add_node(source)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()

    def marker(name, identifier=3):
        return (
            next(
                (m for m in frames[-1].markers if m.ns == labels[name] and m.id == identifier), None
            )
            if frames
            else None
        )

    try:
        wait(lambda: all(marker(n) and marker(n).action == Marker.ADD for n in topics), 8)
        yield view, settings, marker, topics, labels
    finally:
        executor.shutdown(timeout_sec=3)
        thread.join(3)
        view.destroy_node()
        source.destroy_node()
        rclpy.shutdown()


def test_two_sensor_vectors_use_si_units_without_orientation_or_gyro(dual_stack):
    view, settings, marker, topics, labels = dual_stack
    for name, sign in (("Axiom", -1), ("Marty", 1)):
        assert math.isclose(marker(name).points[-1].z, sign * 9.80665 * 0.025, abs_tol=1e-6)
        assert marker(name).header.frame_id == name.lower() + "_acceleration_display"
        assert labels[name] in marker(name, 4).text and "9.81m/s^2" in marker(name, 4).text
        assert "Gyro" not in marker(name, 4).text
    assert not list(view.clients), "Visualization must not control or query devices"
    assert {s.topic_name for s in view.subscriptions} == set(topics.values())


def test_stale_invalid_and_replayed_input_remove_only_that_sensor(dual_stack):
    view, settings, marker, topics, labels = dual_stack
    settings["Marty"]["streaming"] = False
    wait(lambda: marker("Marty").action == Marker.DELETE, 4)
    assert marker("Axiom").action == Marker.ADD
    assert "unavailable" in marker("Marty", 4).text
    settings["Marty"]["streaming"] = True
    wait(lambda: marker("Marty").action == Marker.ADD)
    settings["Axiom"]["covariance"] = -1.0
    wait(lambda: marker("Axiom").action == Marker.DELETE)
    assert marker("Marty").action == Marker.ADD
    settings["Axiom"]["covariance"] = 0.0
    wait(lambda: marker("Axiom").action == Marker.ADD)
    settings["Axiom"]["acceleration"] = (float("nan"), 0.0, 0.0)
    wait(lambda: marker("Axiom").action == Marker.DELETE)
    settings["Axiom"]["acceleration"] = (3.0, 4.0, 0.0)
    wait(lambda: marker("Axiom").action == Marker.ADD)
    wait(lambda: "5.00m/s^2" in marker("Axiom", 4).text)
    settings["Axiom"]["stamp"] = view.get_clock().now().to_msg()
    wait(lambda: marker("Axiom").action == Marker.DELETE, 4)
    assert marker("Marty").action == Marker.ADD
