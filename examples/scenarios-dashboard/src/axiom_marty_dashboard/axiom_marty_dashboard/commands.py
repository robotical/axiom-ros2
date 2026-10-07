"""Console commands only. Nothing in the guide executes ROS commands."""

import json
import os
import re
import shlex

from .command_help import explain


def recipes(state, axiom_namespace="/axiom"):
    root = "/" + axiom_namespace.strip("/")
    rows = []
    thermal_topics = sorted({
        t["name"] for t in state.get("graph", {}).get("topics", [])
        if t["name"].startswith(root + "/bus_")
        and t["name"].endswith("/thermal/grid")
        and "axiom_interfaces/msg/ThermalGrid" in t.get("types", [])
        and t.get("publishers")
    })
    thermal_topic = (thermal_topics[0] if len(thermal_topics) == 1 else
                     root + "/bus_BUS/device_ADDRESS/thermal/grid")

    def add(group, title, command, note=""):
        rows.append(
            dict(group=group, title=title, command=command, note=note, help=explain(title, command))
        )

    def service(group, title, path, kind, payload=None, note=""):
        add(
            group,
            title,
            f"ros2 service call {path} {kind} " + shlex.quote(json.dumps(payload or {})),
            note,
        )

    boards = json.loads(os.environ.get("AXIOM_ROS_BOARDS", "{}"))
    board = boards.get(root.strip("/"), {})
    transport = shlex.quote(board["transport"]) if board else '"${AXIOM_ROS_TRANSPORT:-serial}"'
    uri = shlex.quote(board["device_uri"]) if board else '"${AXIOM_ROS_URI:-ws://192.168.1.7/ws}"'
    add(
        "Start nodes",
        "Axiom driver",
        "ros2 launch axiom_driver axiom_minimal_launch.py "
        f"namespace:={root} "
        'params_file:="$(ros2 pkg prefix --share axiom_driver)/config/hotplug.yaml" '
        f"transport:={transport} device_uri:={uri} "
        'serial.port:="${AXIOM_ROS_SERIAL_PORT:-/dev/ttyACM0}" '
        "auto_connect:=false auto_reconnect:=false autosub:=false",
        "Keep running. The optional aliases are /imu/data_raw and /range beneath this board.",
    )
    add(
        "Start nodes",
        "Multiple Axiom drivers",
        "ros2 launch axiom_driver multi_axiom.launch.py "
        'boards_file:="${AXIOM_ROS_BOARDS_FILE:-$(ros2 pkg prefix '
        '--share axiom_driver)/config/two_axioms.yaml}"',
        "Edit each board connection in YAML first. Every driver starts disconnected.",
    )
    add(
        "Start nodes",
        "Configure USB + Wi-Fi Axioms",
        'cat > "$HOME/usb_wifi_axioms.yaml" <<EOF\n'
        "axioms:\n"
        "  axiom/front:\n"
        '    transport: "${AXIOM_ROS_TRANSPORT:-serial}"\n'
        '    serial.port: "${AXIOM_ROS_SERIAL_PORT:-/dev/ttyACM0}"\n'
        '    device_uri: "${AXIOM_ROS_URI:-}"\n'
        "    auto_connect: true\n"
        "    auto_reconnect: false\n"
        "    autosub: true\n"
        "    publish_rate_hz: 20.0\n"
        "    topic_aliases:\n"
        "      imu/data_raw: {type: LSM6DS, source: imu/data_raw}\n"
        "      range: {type: VL53L4CD, source: range}\n"
        "  axiom/rear:\n"
        "    transport: ws\n"
        '    device_uri: "ws://${AXIOM_WIFI_IP:-192.168.1.11}/ws"\n'
        "    auto_connect: true\n"
        "    auto_reconnect: false\n"
        "    autosub: true\n"
        "    publish_rate_hz: 20.0\n"
        "    topic_aliases:\n"
        "      imu/data_raw: {type: LSM6DS, source: imu/data_raw}\n"
        "      range: {type: VL53L4CD, source: range}\n"
        "EOF",
        "Writes a local configuration. USB is front; Wi-Fi is rear.",
    )
    add(
        "Start nodes",
        "USB + Wi-Fi Axiom drivers",
        "ros2 launch axiom_driver multi_axiom.launch.py "
        'boards_file:="$HOME/usb_wifi_axioms.yaml"',
        "Create the USB + Wi-Fi configuration first. Both drivers connect and acquire at startup.",
    )
    add(
        "Start nodes",
        "Marty driver",
        "ros2 run marty_driver marty_driver_node --ros-args -r __ns:=/marty "
        '-p method:="${MARTY_ROS_METHOD:-usb}" -p locator:="${MARTY_ROS_LOCATOR:-/dev/ttyUSB0}" '
        '-p wifi_port:="${MARTY_ROS_WIFI_PORT:-80}" '
        "-p auto_connect:=false -p auto_reconnect:=false",
    )
    add(
        "Visualize",
        "RViz marker adapter",
        "ros2 run axiom_marty_demo sensor_view --ros-args -r __ns:=/sensing "
        f"-p axiom_namespace:={root}",
        "Reads inventory and sensor topics directly.",
    )
    add(
        "Visualize",
        "RViz",
        'ros2 run rviz2 rviz2 -d "$(ros2 pkg prefix --share axiom_marty_demo)/config/sensors.rviz"',
    )
    add(
        "Inspect",
        "Thermal grid readings",
        f"ros2 topic echo {thermal_topic} axiom_interfaces/msg/ThermalGrid "
        "--qos-reliability best_effort --once",
        "One frame: dimensions, frame ID and pixel temperatures in °C. "
        "Replace BUS/ADDRESS from the topic list if placeholders are shown.",
    )
    add(
        "Inspect",
        "Read thermal frame",
        f'THERMAL_FRAME="$(ros2 topic echo {thermal_topic} '
        "axiom_interfaces/msg/ThermalGrid --field header.frame_id "
        "--qos-reliability best_effort --once | sed -n '1p')\"\n"
        'printf \'%s\\n\' "$THERMAL_FRAME"',
        "Run in the same terminal as Thermal camera RViz. Waits for one live frame.",
    )
    add(
        "Visualize",
        "Thermal heatmap adapter",
        "ros2 run axiom_thermal_viz thermal_heatmap --ros-args -r __ns:=/sensing "
        f"-p input_topic:={thermal_topic} -p output_topic:=thermal_heatmap "
        "-p use_dynamic_range:=false -p min_temperature:=15.0 -p max_temperature:=40.0",
        "Fixed 15–40 °C colour scale. Keep running in Terminal 3.",
    )
    add(
        "Visualize",
        "Thermal camera RViz",
        'ros2 run rviz2 rviz2 -d "$(ros2 pkg prefix --share axiom_marty_demo)/config/thermal.rviz" '
        '-f "${THERMAL_FRAME:?Run Read thermal frame in this terminal first}"',
        "Read thermal frame in this terminal first. Blue is cooler, red is warmer.",
    )
    add(
        "Visualize",
        "Dual accelerometer adapter",
        "ros2 run axiom_marty_demo accelerometer_view --ros-args -r __ns:=/sensing "
        f"-p axiom_topic:={root}/imu/data_raw -p marty_topic:=/marty/imu/data_raw",
    )
    add(
        "Visualize",
        "Dual accelerometer RViz",
        "ros2 run rviz2 rviz2 -d "
        '"$(ros2 pkg prefix --share axiom_marty_demo)/config/accelerometers.rviz"',
    )
    add(
        "Visualize",
        "Two Axiom accelerometer adapter",
        "ros2 run axiom_marty_demo accelerometer_view --ros-args -r __ns:=/sensing "
        "-p axiom_topic:=/axiom/front/imu/data_raw -p marty_topic:=/axiom/rear/imu/data_raw "
        '-p axiom_label:="Axiom USB" -p marty_label:="Axiom Wi-Fi"',
        "Reads both Axiom IMU topics and publishes labelled acceleration arrows.",
    )
    add(
        "Visualize",
        "Two Axiom RViz",
        "ros2 run rviz2 rviz2 -d "
        '"$(ros2 pkg prefix --share axiom_marty_demo)/config/accelerometers.rviz"',
    )
    for title, name, kind, payload in (
        ("Connect Axiom", "connect", "Connect", {"device_uri": ""}),
        ("Disconnect Axiom", "disconnect", "Disconnect", {}),
        ("Axiom connection state", "get_connection_state", "GetConnectionState", {}),
        ("Ping Axiom", "ping", "Ping", {"payload_size": 0}),
        (
            "Axiom REST request",
            "ric_rest_url",
            "RicRestUrl",
            {"url_path": "v", "timeout": 2.0, "ws_pcol": ""},
        ),
    ):
        service("Connection", title, root + "/" + name, "axiom_interfaces/srv/" + kind, payload)
    for title, rate in (("Start Axiom acquisition", 20.0), ("Stop Axiom acquisition", 0.0)):
        service(
            "Acquisition",
            title,
            root + "/publish_data_subscription",
            "axiom_interfaces/srv/PublishedDataSubscription",
            {"rate_hz": rate},
            "Firmware delivery and ROS topic subscriptions are separate.",
        )
    for title, name in (
        ("Connect Marty", "connect"),
        ("Disconnect Marty", "disconnect"),
        ("Marty stop", "stop"),
    ):
        service("Marty", title, "/marty/" + name, "std_srvs/srv/Trigger")
    for title, command in (
        ("Node list", "ros2 node list --no-daemon"),
        ("Node details", f"ros2 node info {root}/axiom_bridge_node"),
        ("Topic list", "ros2 topic list -t --no-daemon"),
        ("Service list", "ros2 service list -t"),
        ("Action list", "ros2 action list -t"),
        ("Sensor inventory", f"ros2 topic echo {root}/devices --qos-durability transient_local"),
        (
            "Device descriptors",
            f"ros2 topic echo {root}/device_metadata --qos-durability transient_local",
        ),
        (
            "Accelerometer readings",
            f"ros2 topic echo {root}/imu/data_raw sensor_msgs/msg/Imu "
            "--field linear_acceleration --qos-reliability best_effort",
        ),
        (
            "Distance readings",
            f"ros2 topic echo {root}/range sensor_msgs/msg/Range "
            "--field range --qos-reliability best_effort",
        ),
        (
            "Marty accelerometer readings",
            "ros2 topic echo /marty/imu/data_raw sensor_msgs/msg/Imu "
            "--field linear_acceleration --qos-reliability best_effort",
        ),
        ("Marty status", "ros2 topic echo /marty/status --qos-durability transient_local"),
        ("Parameters", f"ros2 param dump {root}/axiom_bridge_node"),
        ("Motion interface", "ros2 interface show marty_interfaces/action/Motion"),
        (
            "Record telemetry",
            f"ros2 bag record {root}/devices {root}/imu/data_raw {root}/range /marty/imu/data_raw",
        ),
    ):
        add("Inspect", title, command)
    for device in state.get("devices", []):
        if not device.get("online") or device.get("stale"):
            continue
        for item in device.get("commands", []):
            action = item["descriptor"]
            if action.get("f") == "LEDPIX":
                values = [0, 16, 16, 16]
            elif action.get("t"):
                # Configuration maps use Hz, not the raw integer format.
                count = sum(
                    int(n or 1) for n, _ in re.findall(r"([0-9]*)([bBhHiIlLqQfd?])", action["t"])
                )
                value = action.get("d", action.get("r", [0])[0])
                if action.get("r") and not action["r"][0] <= value <= action["r"][1]:
                    value = action["r"][0]
                values = [value] * count
            else:
                values = []
            service(
                "Device commands",
                device["type"] + " · " + item["name"],
                root + "/" + item["service"],
                "axiom_interfaces/srv/DeviceCommand",
                {"values": values},
                action.get("desc", "Firmware acknowledgment; not physical completion."),
            )
            rows[-1]["help"]["description"] = action.get(
                "desc", "Runs the command advertised by this live device descriptor."
            )
            for label, value in (
                ("Allowed range", action.get("r")),
                ("Allowed values", list(action.get("map", {}))),
                ("Numeric format", action.get("t") if item["name"] != "_conf.rate" else None),
            ):
                if value:
                    rows[-1]["help"]["arguments"].append(dict(name=label, description=str(value)))
            if action.get("f") == "LEDPIX":
                rows[-1]["help"]["arguments"].append(
                    dict(name="values order", description="Pixel index, red, green, blue.")
                )
    for title, goal in (
        (
            "Walk one step",
            dict(command=0, num_steps=1, side="auto", step_length_mm=20, turn_degrees=0),
        ),
        ("Dance", dict(command=1, side="left")),
        ("Kick", dict(command=2, side="left")),
        ("Stand", dict(command=3)),
        ("Move eyebrows", dict(command=4, joint_id=8, position_degrees=0)),
    ):
        add(
            "Marty motion",
            title,
            "ros2 action send_goal /marty/motion marty_interfaces/action/Motion "
            + shlex.quote(json.dumps({**goal, "move_time_ms": 1200}))
            + " --feedback",
        )
    return rows
