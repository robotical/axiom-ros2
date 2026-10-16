"""Real DDS input drives RViz; invalid, stale or disconnected input must disappear."""

from collections import deque
import json
import math
import threading
import time

import pytest

rclpy = pytest.importorskip("rclpy")
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data  # noqa: E402
from sensor_msgs.msg import Imu, Range  # noqa: E402
from std_msgs.msg import String  # noqa: E402
from visualization_msgs.msg import Marker, MarkerArray  # noqa: E402
from axiom_marty_demo.sensor_view import SensorView  # noqa: E402


def wait(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Sensor viewer condition did not become true")


@pytest.fixture
def view_stack():
    rclpy.init()
    view, source = SensorView(namespace="view_test"), Node("view_source")
    retained = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
    inventory = source.create_publisher(String, "/axiom/devices", retained)
    range_pub = source.create_publisher(
        Range, "/axiom/vl53l4cd_b1_129/range", qos_profile_sensor_data
    )
    imu_pub = source.create_publisher(
        Imu, "/axiom/lsm6ds_b1_76a/data_raw", qos_profile_sensor_data
    )
    frames = deque(maxlen=5)
    source.create_subscription(
        MarkerArray,
        "/view_test/visualization/markers",
        lambda m: frames.append(m),
        qos_profile_sensor_data,
    )
    settings = {
        "connected": True,
        "range": 0.4,
        "fov": 0.3,
        "streaming": True,
        "selected": "vl53l4cd_b1_129",
        "imu_topic": "lsm6ds_b1_76a",
    }

    def publish():
        rows = [
            {
                "topic": "vl53l4cd_b1_129",
                "type": "VL53L4CD",
                "online": settings["connected"],
                "metadata_ready": True,
                "public_topics": {
                    "x": {"range": "vl53l4cd_b1_129/range"}
                },
            },
            {
                "topic": settings["imu_topic"],
                "type": "LSM6DS",
                "online": settings["connected"],
                "metadata_ready": True,
                "public_topics": {
                    "x": {"data_raw": settings["imu_topic"] + "/data_raw"}
                },
            },
        ]
        inventory.publish(String(data=json.dumps(rows)))
        if not settings["streaming"]:
            return
        stamp = source.get_clock().now().to_msg()
        range_msg = Range(
            min_range=0.0, max_range=1.0, range=settings["range"], field_of_view=settings["fov"]
        )
        range_msg.header.stamp = stamp
        range_pub.publish(range_msg)
        imu_msg = Imu()
        imu_msg.header.stamp = stamp
        imu_msg.orientation_covariance[0] = -1.0
        imu_msg.linear_acceleration.z = -9.80665
        imu_pub.publish(imu_msg)

    source.create_timer(0.1, publish)
    executor = SingleThreadedExecutor()
    executor.add_node(view)
    executor.add_node(source)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()

    def marker(id):
        return next((m for m in frames[-1].markers if m.id == id), None) if frames else None

    try:
        wait(lambda: marker(20) and marker(20).action == Marker.ADD, 8)
        yield view, settings, marker
    finally:
        executor.shutdown(timeout_sec=3)
        thread.join(3)
        view.destroy_node()
        source.destroy_node()
        rclpy.shutdown()


def test_real_range_cone_and_acceleration_vector_use_sensor_units(view_stack):
    view, settings, marker = view_stack
    wait(lambda: marker(10) and marker(10).action == Marker.ADD)
    assert math.isclose(max(p.x for p in marker(20).points), 0.4, abs_tol=1e-6)
    assert math.isclose(marker(10).points[-1].z, -9.80665 * 0.025, abs_tol=1e-6)
    assert marker(10).lifetime.nanosec == 400_000_000
    assert "m/s^2" in marker(11).text
    assert not list(view.clients), "The viewer must not create robot command clients"


def test_invalid_stale_and_disconnected_sources_remove_live_geometry(view_stack):
    view, settings, marker = view_stack
    settings["range"] = float("nan")
    wait(lambda: marker(20).action == Marker.DELETE)
    assert "unavailable" in marker(21).text
    settings["range"] = 0.5
    wait(lambda: marker(20).action == Marker.ADD)
    settings["streaming"] = False
    wait(lambda: marker(20).action == Marker.DELETE and marker(10).action == Marker.DELETE, 4)
    settings["streaming"] = True
    wait(lambda: marker(20).action == Marker.ADD)
    settings["connected"] = False
    wait(lambda: marker(20).action == Marker.DELETE and marker(10).action == Marker.DELETE)
    assert "disconnected" in marker(21).text
    settings["connected"] = True
    wait(lambda: marker(20).action == Marker.ADD)


def test_changing_selected_sensor_never_displays_previous_source(view_stack):
    view, settings, marker = view_stack
    from rclpy.parameter import Parameter

    view.set_parameters([Parameter("range_sensor", value="vl53l4cd_b2_129")])
    wait(lambda: marker(20).action == Marker.DELETE)
    assert "unavailable" in marker(21).text


def test_driver_default_unspecified_fov_keeps_valid_distance(view_stack):
    view, settings, marker = view_stack
    settings["fov"] = 0.0
    wait(lambda: marker(20).type == Marker.ARROW and marker(20).action == Marker.ADD)
    assert math.isclose(marker(20).points[-1].x, 0.4, abs_tol=1e-6)
    assert "40.0cm" in marker(21).text
    assert "FoV:unspecified" in marker(21).text


def test_replacing_imu_clears_old_source_and_rejects_queued_frames(view_stack):
    view, settings, marker = view_stack
    wait(lambda: marker(10).action == Marker.ADD)
    old_device = view.devices["lsm6ds_b1_76a"]
    settings["imu_topic"] = "lsm6ds_b2_76a"
    wait(lambda: "lsm6ds_b1_76a" not in view.devices)
    stale = Imu()
    stale.header.stamp = view.get_clock().now().to_msg()
    stale.linear_acceleration.z = 3.0
    view._imu(old_device, stale)
    assert view.imu_source != "lsm6ds_b1_76a"
    new = view.devices["lsm6ds_b2_76a"]
    view._imu(new, stale)
    wait(
        lambda: (
            marker(10).action == Marker.ADD
            and math.isclose(marker(10).points[-1].z, 3.0 * 0.025, abs_tol=1e-6)
        )
    )
    assert view.imu_source == "lsm6ds_b2_76a"


def test_unresolved_rows_and_late_output_inventory_do_not_hide_ready_sensors():
    rclpy.init()
    view = SensorView(namespace="inventory_test")
    imu = dict(topic="lsm6ds_b1_76a", type="LSM6DS", online=True,
               metadata_ready=True, public_topics={})
    unresolved = dict(topic=None, type="3", online=True, metadata_ready=False)
    ranging = dict(topic="vl53l4cd_b2_29", type="VL53L4CD", online=True,
                   metadata_ready=True, aliases=["front/range"], public_topics={
                       "x": {"range": "vl53l4cd_b2_29/range"}})

    def inventory():
        view._inventory(String(data=json.dumps([unresolved, imu, ranging])))

    try:
        inventory()
        assert view.connected and set(view.devices) == {imu["topic"], ranging["topic"]}
        assert not view.devices[imu["topic"]]["subscriptions"]
        range_subscription = view.devices[ranging["topic"]]["subscriptions"]["range"]
        assert range_subscription.topic_name == "/axiom/vl53l4cd_b2_29/range"
        assert not any(sub.topic_name == "/axiom/front/range" for sub in view.subscriptions)
        # Metadata can be ready before the first sample creates a canonical output.
        imu["public_topics"] = {"x": {"data_raw": "lsm6ds_b1_76a/data_raw"}}
        inventory()
        assert view.devices[imu["topic"]]["subscriptions"]["data_raw"].topic_name == (
            "/axiom/lsm6ds_b1_76a/data_raw")
        imu["public_topics"] = {}
        inventory()
        assert not view.devices[imu["topic"]]["subscriptions"]
        imu["online"] = False
        inventory()
        assert set(view.devices) == {ranging["topic"]}
        assert view.devices[ranging["topic"]]["subscriptions"]["range"] is range_subscription
    finally:
        view.destroy_node()
        rclpy.shutdown()
