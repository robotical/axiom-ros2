"""The optional observer may start late or disappear without controlling ROS."""

import json
import threading
import time
from urllib.request import urlopen

import pytest

rclpy = pytest.importorskip("rclpy")
from axiom_marty_dashboard.node import Dashboard, DriverStatus  # noqa: E402
from axiom_interfaces.srv import GetConnectionState  # noqa: E402
from axiom_interfaces.srv import DeviceCommand  # noqa: E402
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy  # noqa: E402
from rosidl_runtime_py.utilities import get_message  # noqa: E402
from std_msgs.msg import String  # noqa: E402


def wait(predicate, timeout=6):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("Timed out")


@pytest.mark.parametrize("include_marty", [False, True])
def test_discovery_includes_custom_topics_endpoints_and_removal_without_core(
    monkeypatch, include_marty
):
    if include_marty and DriverStatus is None:
        pytest.skip("Optional Marty interfaces are not installed")
    if not include_marty:
        monkeypatch.setattr("axiom_marty_dashboard.node.DriverStatus", None)
    rclpy.init()
    observer = Dashboard(parameter_overrides=[Parameter("port", value=0)])
    producer = rclpy.create_node("producer", namespace="lesson")
    consumer = rclpy.create_node("consumer", namespace="lesson")
    qos = QoSProfile(
        depth=1,
        reliability=ReliabilityPolicy.BEST_EFFORT,
        durability=DurabilityPolicy.VOLATILE,
    )
    producer.create_publisher(String, "/lesson/readings", qos)
    for _ in range(2):
        consumer.create_subscription(String, "/lesson/readings", lambda _: None, qos)
    consumer.create_subscription(String, "/lesson/waiting", lambda _: None, qos)
    executor = SingleThreadedExecutor()
    for node in (observer, producer, consumer):
        executor.add_node(node)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()
    producer_alive = consumer_alive = True
    url = "http://127.0.0.1:" + str(observer.panel.server.server_port)

    def snapshot():
        with urlopen(url + "/api/state", timeout=2) as response:
            return json.load(response)

    def topic(name):
        return next((t for t in snapshot()["graph"]["topics"] if t["name"] == name), {})

    try:
        wait(lambda: len(topic("/lesson/readings").get("subscriber_endpoints", [])) == 2)
        readings = topic("/lesson/readings")
        assert readings["publishers"] == ["/lesson/producer"]
        assert readings["subscribers"] == ["/lesson/consumer"]
        assert readings["types"] == ["std_msgs/msg/String"]
        assert not readings["infrastructure"]
        assert readings["publisher_endpoints"][0]["reliability"] == "BEST_EFFORT"
        assert readings["subscriber_endpoints"][0]["durability"] == "VOLATILE"
        wait(lambda: bool(topic("/lesson/waiting")))
        assert topic("/lesson/waiting")["publishers"] == []
        assert topic("/lesson/waiting")["subscribers"] == ["/lesson/consumer"]
        state = snapshot()
        assert state["catalogue"]["nodes"] and state["commands"]
        # Axiom reference types resolve without installing optional Marty packages.
        for node in state["catalogue"]["nodes"]:
            for interface in node["publications"] + node["subscriptions"]:
                for message_type in interface["types"]:
                    if message_type.startswith("marty_interfaces/") and DriverStatus is None:
                        continue
                    get_message(message_type)
        # The guide does not subscribe to discovered sensor or teaching topics.
        assert [
            t["name"]
            for t in state["graph"]["topics"]
            if "/dashboard" in t["subscribers"] and not t["infrastructure"]
        ] == (["/axiom/devices", "/marty/status"] if include_marty else ["/axiom/devices"])
        executor.remove_node(producer)
        producer.destroy_node()
        producer_alive = False
        wait(lambda: topic("/lesson/readings").get("publishers") == [])
        wait(lambda: "/lesson/producer" not in snapshot()["graph"]["nodes"])
        executor.remove_node(consumer)
        consumer.destroy_node()
        consumer_alive = False
        wait(lambda: not topic("/lesson/readings") and not topic("/lesson/waiting"))
        assert snapshot()["catalogue"]["nodes"]
    finally:
        executor.shutdown(timeout_sec=3)
        thread.join(3)
        observer.close()
        observer.destroy_node()
        if producer_alive:
            producer.destroy_node()
        if consumer_alive:
            consumer.destroy_node()
        rclpy.shutdown()


def test_two_board_discovery_keeps_guidance_and_descriptor_services_separate():
    rclpy.init()
    observer = Dashboard(parameter_overrides=[Parameter("port", value=0)])
    drivers = [
        rclpy.create_node("driver", namespace="/axiom/" + name) for name in ("front", "rear")
    ]
    states = [True, False]
    queries = []
    for index, driver in enumerate(drivers):

        def connection(_request, response, index=index):
            queries.append(index)
            response.connected = states[index]
            return response

        driver.create_service(GetConnectionState, "get_connection_state", connection)
        driver.create_service(
            DeviceCommand, "bus_1/device_23/commands/brightness", lambda request, response: response
        )
        inventory = driver.create_publisher(
            String, "devices", QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        )
        row = dict(
            topic="bus_1/device_23",
            type="QwiicLEDStick",
            online=True,
            metadata_ready=True,
            commands=[
                dict(
                    name="brightness",
                    service="bus_1/device_23/commands/brightness",
                    descriptor={"n": "brightness", "t": "B", "r": [0, 255]},
                )
            ],
        )
        inventory.publish(String(data=json.dumps([row])))
    executor = SingleThreadedExecutor()
    for node in [observer, *drivers]:
        executor.add_node(node)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()
    url = "http://127.0.0.1:" + str(observer.panel.server.server_port)

    def snapshot():
        with urlopen(url + "/api/state", timeout=2) as response:
            return json.load(response)

    try:
        wait(
            lambda: (
                len(snapshot()["boards"]) == 2 and all(b["available"] for b in snapshot()["boards"])
            )
        )
        boards = {b["namespace"]: b for b in snapshot()["boards"]}
        assert boards["/axiom/front"]["connected"]
        assert not boards["/axiom/rear"]["connected"]
        states[1] = True
        wait(lambda: all(b["connected"] for b in snapshot()["boards"]))
        wait(lambda: all(b["devices"] for b in snapshot()["boards"]))
        payload = snapshot()
        for root, guide in payload["guides"].items():
            commands = [c["command"] for c in guide["commands"] if c["group"] == "Device commands"]
            assert (
                len(commands) == 1 and root + "/bus_1/device_23/commands/brightness" in commands[0]
            )
        wait(lambda: any(s.get("descriptor") for s in snapshot()["graph"]["services"]))
        services = [s for s in snapshot()["graph"]["services"] if s.get("descriptor")]
        assert len(services) == 2
        assert all(s["descriptor"]["r"] == [0, 255] for s in services)
        assert set(queries) == {0, 1}
        assert all(
            name.endswith("/get_connection_state")
            for name, _ in observer.get_client_names_and_types_by_node("dashboard", "/")
        )
    finally:
        executor.shutdown(timeout_sec=3)
        thread.join(3)
        observer.close()
        for node in [observer, *drivers]:
            node.destroy_node()
        rclpy.shutdown()


@pytest.mark.skipif(DriverStatus is None, reason="Optional Marty interfaces are not installed")
def test_driver_connection_status_without_demo_and_stale_status_is_invalidated():
    rclpy.init()
    observer = Dashboard(parameter_overrides=[Parameter("port", value=0)])
    driver = rclpy.create_node("status_test_driver")
    connected = False
    queries = []

    def connection(_request, response):
        queries.append("get_connection_state")
        response.connected = connected
        response.last_error = "" if connected else "USB disconnected"
        return response

    driver.create_service(GetConnectionState, "/axiom/get_connection_state", connection)
    publisher = driver.create_publisher(
        DriverStatus,
        "/marty/status",
        QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL),
    )
    timer = driver.create_timer(0.1, lambda: publisher.publish(DriverStatus(connected=connected)))
    executor = SingleThreadedExecutor()
    for node in (observer, driver):
        executor.add_node(node)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()
    driver_alive = True
    url = "http://127.0.0.1:" + str(observer.panel.server.server_port)

    def snapshot():
        with urlopen(url + "/api/state", timeout=2) as response:
            return json.load(response)

    try:
        wait(lambda: all(c["available"] for c in snapshot()["connections"].values()))
        assert snapshot()["connections"]["axiom"]["state"] == "disconnected"
        connected = True
        wait(lambda: all(c["connected"] for c in snapshot()["connections"].values()))
        timer.cancel()
        wait(lambda: snapshot()["connections"]["marty"]["state"] == "status unavailable")
        assert not snapshot()["connections"]["marty"]["connected"]
        timer.reset()
        connected = False
        wait(lambda: all(c["state"] == "disconnected" for c in snapshot()["connections"].values()))
        executor.remove_node(driver)
        driver.destroy_node()
        driver_alive = False
        wait(
            lambda: all(c["state"] == "driver offline" for c in snapshot()["connections"].values())
        )
        assert queries and set(queries) == {"get_connection_state"}
        assert [
            name
            for name, _ in observer.get_client_names_and_types_by_node(
                observer.get_name(), observer.get_namespace()
            )
        ] == ["/axiom/get_connection_state"]
    finally:
        executor.shutdown(timeout_sec=3)
        thread.join(3)
        observer.close()
        observer.destroy_node()
        if driver_alive:
            driver.destroy_node()
        rclpy.shutdown()
