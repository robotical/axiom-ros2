"""Small reference graph for the manual sensor and robot workflow."""

from .commands import recipes


def catalogue(axiom_namespace="/axiom"):
    root = "/" + axiom_namespace.strip("/")
    commands = {r["title"]: r for r in recipes({}, root)}
    nodes, topics = [], []

    def node(name, title, role, recipe=None):
        command = commands.get(recipe or title, {})
        row = dict(
            name=name,
            title=title,
            role=role,
            publications=[],
            subscriptions=[],
            services=[],
            actions=[],
            command=command.get("command", ""),
            help=command.get("help", {}),
        )
        nodes.append(row)
        return row

    axiom = node(
        root + "/axiom_bridge_node",
        "Axiom driver",
        "Discovers supported sensors and descriptor commands after explicit acquisition.",
    )
    marty = node("/marty/marty_driver", "Marty driver", "Robot connection and telemetry.")
    view = node(
        "/sensing/sensor_view", "RViz marker adapter", "Discovered IMU and distance readings."
    )
    dual = node(
        "/sensing/accelerometer_view",
        "Dual accelerometer adapter",
        "Axiom and Marty acceleration vectors.",
    )
    rviz = node("/rviz2", "RViz", "Native ROS visualization.")
    guide = node("/dashboard", "Browser guide", "Optional inventory, status and graph observer.")
    echo = node(
        "/ros2cli_*",
        "Topic echo",
        "A subscriber for the topic you choose.",
        "Accelerometer readings",
    )
    bag = node("/rosbag2_recorder", "Bag recorder", "Records requested topics.", "Record telemetry")

    def topic(name, kind, publisher, consumers=(), note="", retained=False, diagram=True):
        contract = dict(name=name, types=[kind], note=note, retained=retained)
        publisher["publications"].append(contract)
        for consumer in consumers:
            consumer["subscriptions"].append(contract)
        if diagram:
            topics.append(
                {
                    **contract,
                    "publishers": [publisher["name"]],
                    "subscribers": [n["name"] for n in consumers],
                }
            )

    topic(
        root + "/devices",
        "std_msgs/msg/String",
        axiom,
        [view, guide],
        "Retained device inventory, aliases and descriptor commands.",
        retained=True,
    )
    topic(
        root + "/device_metadata",
        "std_msgs/msg/String",
        axiom,
        note="Firmware descriptors and profile revisions.",
        retained=True,
        diagram=False,
    )
    for name, kind in (("imu/data_raw", "Imu"), ("range", "Range")):
        topic(
            root + "/bus_BUS/device_ADDRESS/" + name,
            "sensor_msgs/msg/" + kind,
            axiom,
            [view],
            "Identity-based topic; appears for a supported, online sensor.",
        )
        topic(
            root + "/" + name,
            "sensor_msgs/msg/" + kind,
            axiom,
            [dual] if name.startswith("imu") else [],
            "Optional alias; published only when one configured sensor matches.",
            diagram=False,
        )
    for suffix, kind in (
        ("sample", "axiom_interfaces/msg/DeviceSample"),
        ("data", "std_msgs/msg/String"),
        ("thermal/grid", "axiom_interfaces/msg/ThermalGrid"),
        ("temperature", "sensor_msgs/msg/Temperature"),
        ("humidity", "sensor_msgs/msg/RelativeHumidity"),
        ("joint_states", "sensor_msgs/msg/JointState"),
        ("battery", "sensor_msgs/msg/BatteryState"),
    ):
        topic(root + "/bus_BUS/device_ADDRESS/" + suffix, kind, axiom, diagram=False)
    topic(root + "/diagnostics", "diagnostic_msgs/msg/DiagnosticArray", axiom, diagram=False)
    topic(root + "/raw/devjson", "std_msgs/msg/String", axiom, diagram=False)
    topic(root + "/serial_console", "std_msgs/msg/String", axiom, diagram=False)
    topic("/marty/status", "marty_interfaces/msg/DriverStatus", marty, [guide], retained=True)
    topic("/marty/imu/data_raw", "sensor_msgs/msg/Imu", marty, [dual])
    for suffix, kind in (
        ("joint_states", "sensor_msgs/msg/JointState"),
        ("battery", "sensor_msgs/msg/BatteryState"),
        ("servo_states", "marty_interfaces/msg/ServoStates"),
        ("telemetry", "marty_interfaces/msg/Telemetry"),
    ):
        topic("/marty/" + suffix, kind, marty, diagram=False)
    topic("/sensing/visualization/markers", "visualization_msgs/msg/MarkerArray", view, [rviz])
    topic(
        "/sensing/visualization/accelerometers", "visualization_msgs/msg/MarkerArray", dual, [rviz]
    )
    for producer in (view, dual):
        topic(
            "/tf_static", "tf2_msgs/msg/TFMessage", producer, [rviz], retained=True, diagram=False
        )
    axiom["services"] = [
        dict(name=root + "/" + name, type="axiom_interfaces/srv/" + kind, role="server")
        for name, kind in (
            ("connect", "Connect"),
            ("disconnect", "Disconnect"),
            ("get_connection_state", "GetConnectionState"),
            ("ping", "Ping"),
            ("ric_rest_url", "RicRestUrl"),
            ("publish_data_subscription", "PublishedDataSubscription"),
            ("set_sample_rate", "SetSampleRate"),
        )
    ]
    axiom["services"].append(
        dict(
            name=root + "/bus_BUS/device_ADDRESS/commands/COMMAND",
            type="axiom_interfaces/srv/DeviceCommand",
            role="server",
            note="Created from the live descriptor; removed when the device goes offline.",
        )
    )
    marty["services"] = [
        dict(name="/marty/" + name, type="std_srvs/srv/Trigger", role="server")
        for name in ("connect", "disconnect", "stop")
    ]
    marty["actions"] = [
        dict(name="/marty/motion", type="marty_interfaces/action/Motion", role="server")
    ]
    guide["services"] = [
        dict(
            name=root + "/get_connection_state",
            type="axiom_interfaces/srv/GetConnectionState",
            role="client",
        )
    ]
    echo["subscriptions"] = [
        dict(name="A topic you choose", types=[], note="Sensor QoS: Best Effort.")
    ]
    bag["subscriptions"] = [dict(name="Topics you choose", types=[])]
    return dict(nodes=nodes, topics=topics)
