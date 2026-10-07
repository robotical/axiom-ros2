"""Manual walkthroughs for discovery, descriptor commands and visualization."""

import shlex

from .command_help import explain


def walkthroughs(commands, graph, axiom_namespace="/axiom", devices=()):
    root = "/" + axiom_namespace.strip("/")
    recipes = {r["title"]: r for r in commands}

    def custom(title, command):
        return dict(title=title, command=command, note="", help=explain(title, command))

    def learning(recipe, terminal):
        """Describe what discovery can verify, without inferring command execution."""
        name = recipe["title"] if recipe else ""
        robot = "marty" if "Marty" in name else "axiom"
        namespace = "/marty" if robot == "marty" else root
        node = namespace + ("/marty_driver" if robot == "marty" else "/axiom_bridge_node")
        check = dict(kind="hardware" if terminal is None else "console", terminal=terminal)
        flow = [dict(kind="console", name=f"Terminal {terminal}"),
                dict(kind="action", name="Inspect the result")]
        if name in ("Axiom driver", "Marty driver"):
            check = dict(kind="driver", nodes=[node])
            flow = [dict(kind="console", name=f"Terminal {terminal}"),
                    dict(kind="node", name=node)]
        elif name in ("Connect Axiom", "Connect Marty", "Disconnect Axiom", "Disconnect Marty"):
            check = dict(kind="connection", namespace=namespace,
                         connected=name.startswith("Connect"))
        elif name in ("Start Axiom acquisition", "Stop Axiom acquisition"):
            check = dict(kind="acquisition", namespace=root, terminal=terminal)
        elif name == "USB + Wi-Fi Axiom drivers":
            check = dict(kind="driver", nodes=[
                "/axiom/front/axiom_bridge_node", "/axiom/rear/axiom_bridge_node"])
            flow = [dict(kind="node", name=n) for n in check["nodes"]]
        elif name in ("Topic list", "Service list"):
            check = dict(kind="discovery", namespace=root,
                         collection="topics" if name == "Topic list" else "services")
        if recipe:
            try:
                args = shlex.split(recipe["command"])
            except ValueError:
                args = []
            if args[:3] in (["ros2", "topic", "echo"], ["ros2", "topic", "info"]):
                topic = args[3]
                topic_root = topic.split("/bus_", 1)[0]
                if "/bus_" not in topic:
                    for suffix in ("/imu/data_raw", "/range", "/devices", "/device_metadata",
                                   "/status"):
                        if topic.endswith(suffix):
                            topic_root = topic.removesuffix(suffix)
                            break
                node = topic_root + (
                    "/marty_driver" if topic.startswith("/marty/") else "/axiom_bridge_node"
                )
                check = dict(kind="topic", topic=topic, console=args[2] == "echo",
                             terminal=terminal)
                flow = [dict(kind="node", name=node), dict(kind="topic", name=topic),
                        dict(kind="console", name=f"Terminal {terminal}")]
            elif args[:3] == ["ros2", "service", "call"]:
                service_root = args[3].split("/bus_", 1)[0].rsplit("/", 1)[0]
                if check["kind"] in ("connection", "acquisition"):
                    check["namespace"] = service_root
                    node = service_root + (
                        "/marty_driver" if service_root == "/marty" else "/axiom_bridge_node"
                    )
                flow = [dict(kind="console", name=f"Terminal {terminal}"),
                        dict(kind="service", name=args[3]), dict(kind="node", name=node)]
            elif args[:3] == ["ros2", "run", "axiom_marty_demo"]:
                adapter = "accelerometer_view" if "accelerometer" in args[3] else "sensor_view"
                path = "/sensing/" + adapter
                check = dict(kind="driver", nodes=[path])
                marker_topic = "/sensing/visualization/" + (
                    "accelerometers" if adapter == "accelerometer_view" else "markers"
                )
                flow = [dict(kind="topic", name="Sensor topics"),
                        dict(kind="node", name=path), dict(kind="topic", name=marker_topic)]
            elif args[:3] == ["ros2", "run", "rviz2"]:
                markers = "/sensing/visualization/" + (
                    "accelerometers" if "accelerometers.rviz" in recipe["command"] else "markers"
                )
                flow = [dict(kind="topic", name=markers), dict(kind="action", name="RViz"),
                        dict(kind="action", name="Acceleration arrows")]
        return check, flow

    def step(title, terminal, expected, recipe=None, instruction="", check=None, flow=None):
        observed, relationship = learning(recipe, terminal)
        return dict(
            title=title,
            terminal=terminal,
            expected=expected,
            recipe=recipe,
            instruction=instruction,
            check=check or observed,
            flow=flow or relationship,
        )

    def run(title, terminal, expected):
        return step(title, terminal, expected, recipes[title])

    def stop(terminal, title="Stop this process"):
        return step(
            title,
            terminal,
            "The prompt returns.",
            instruction=f"Press Ctrl+C in Terminal {terminal}.",
            flow=[dict(kind="console", name=f"Terminal {terminal}"),
                  dict(kind="action", name="Ctrl+C"), dict(kind="action", name="Prompt")],
        )

    def sensor_topics(suffix, kind):
        return sorted(
            {
                t["name"]
                for t in graph.get("topics", [])
                if t["name"].startswith(root + "/bus_")
                and t["name"].endswith("/" + suffix)
                and kind in t.get("types", [])
                and t.get("publishers")
            }
        )

    startup = [
        run("Axiom driver", 1, "Driver running; connection and acquisition are off."),
        run("Connect Axiom", 2, "success: true; board connected, acquisition still off."),
        run("Start Axiom acquisition", 2, "success: true; firmware delivery is active."),
    ]
    cleanup = [
        run("Stop Axiom acquisition", 2, "Delivery stops; the board stays connected."),
        run("Disconnect Axiom", 2, "success: true; dynamic interfaces are removed."),
        stop(1, "Stop the driver"),
    ]
    hints = [
        "No data: check connection, acquisition and a Best Effort subscriber.",
        "An alias is absent when no sensor or multiple matching sensors are online. "
        "Use the identity-based topic, or add a bus/address preference in topic_aliases.",
        "A topic name can remain because a subscriber exists. Check ros2 topic info "
        "--verbose for the publisher count.",
    ]

    prerequisites = {
        "accelerometer": ["Axiom", "LSM6DS IMU"],
        "distance": ["Axiom", "Distance sensor"],
        "thermal": ["1 × Axiom", "AMG8833 · 8×8", "RViz"],
        "distance-hotplug": ["USB Axiom powered", "Distance sensor unplugged"],
        "descriptor-config": ["Axiom", "LSM6DS IMU"],
        "marty": ["Marty · USB / Wi-Fi"],
        "dual-accelerometers": ["Axiom + LSM6DS", "Marty"],
        "multiple-axioms": ["USB Axiom · front", "Wi-Fi Axiom · rear", "2 × LSM6DS"],
    }

    def scenario(identifier, title, requires, steps, finish, topics=(), troubleshooting=None):
        return dict(
            id=identifier,
            title=title,
            requires=requires,
            prerequisites=prerequisites[identifier],
            mode="Auto connect + acquire" if identifier == "multiple-axioms" else "Manual console",
            summary="Run each step in the indicated terminal.",
            steps=steps,
            cleanup=finish,
            topics=list(topics),
            troubleshooting=troubleshooting or hints,
        )

    accel = scenario(
        "accelerometer",
        "Axiom · accelerometer + RViz",
        "LSM6DS IMU. The launch command enables its optional stable alias.",
        [
            *startup,
            run(
                "Accelerometer readings",
                3,
                "Acceleration x/y/z in m/s²; gravity is about 9.8 m/s² at rest.",
            ),
            stop(3, "Free Terminal 3 for visualization"),
            run("RViz marker adapter", 3, "Discovered sensor data becomes visualization markers."),
            run("RViz", 4, "Fixed Frame sensor_view. Tilt Axiom to change the acceleration arrow."),
        ],
        [stop(4, "Close RViz"), stop(3, "Stop the marker adapter"), *cleanup],
        sensor_topics("imu/data_raw", "sensor_msgs/msg/Imu"),
    )
    distance = scenario(
        "distance",
        "Axiom · distance readings",
        "Supported distance sensor, e.g. VL53L4CD. The default alias matches that model.",
        [
            *startup,
            run("Distance readings", 3, "Distance in metres. NaN means an invalid measurement."),
        ],
        [stop(3, "Stop the subscriber"), *cleanup],
        sensor_topics("range", "sensor_msgs/msg/Range"),
    )
    thermal_topics = sensor_topics("thermal/grid", "axiom_interfaces/msg/ThermalGrid")
    thermal_topic = (thermal_topics[0] if len(thermal_topics) == 1 else
                     root + "/bus_BUS/device_ADDRESS/thermal/grid")
    thermal = scenario(
        "thermal",
        "Axiom · thermal camera + RViz",
        "One Axiom with an AMG8833 thermal camera attached. Source the ROS workspace "
        "in every terminal. Commands use the discovered camera topic once exactly one "
        "thermal publisher is available; otherwise replace BUS/ADDRESS from the topic list.",
        [
            *startup,
            run("Topic list", 2, "Find the camera's …/thermal/grid topic, "
                "with type axiom_interfaces/msg/ThermalGrid."),
            run("Thermal grid readings", 2, "One 8×8 frame, 64 temperatures in °C "
                "and a nonempty header.frame_id; the prompt returns."),
            step(
                "Read the camera frame for RViz", 4,
                "The sensor frame name is printed and stored in THERMAL_FRAME. "
                "Use this same terminal for RViz.",
                recipes["Read thermal frame"],
                check=dict(kind="topic", topic=thermal_topic, console=False),
                flow=[dict(kind="topic", name=thermal_topic),
                      dict(kind="console", name="Terminal 4 · THERMAL_FRAME")],
            ),
            step(
                "Start the thermal heatmap", 3,
                "The adapter publishes /sensing/thermal_heatmap markers. Keep it running.",
                recipes["Thermal heatmap adapter"],
                check=dict(kind="driver", nodes=["/sensing/thermal_grid_visualizer"]),
                flow=[dict(kind="topic", name=thermal_topic),
                      dict(kind="node", name="/sensing/thermal_grid_visualizer"),
                      dict(kind="topic", name="/sensing/thermal_heatmap")],
            ),
            step(
                "View the thermal camera in RViz", 4,
                "An 8×8 heatmap with small temperature labels in °C. "
                "Move a hand into view: warmer pixels shift toward red "
                "on the fixed 15–40 °C scale; cooler pixels toward blue.",
                recipes["Thermal camera RViz"],
                check=dict(kind="console", terminal=4),
                flow=[dict(kind="topic", name="/sensing/thermal_heatmap"),
                      dict(kind="action", name="RViz · pixel temperatures")],
            ),
        ],
        [stop(4, "Close RViz"), stop(3, "Stop the heatmap adapter"), *cleanup],
        thermal_topics,
        troubleshooting=[
            "No thermal topic: check the camera is online in /devices and acquisition "
            "returned success: true. This scenario targets AMG8833; another model needs "
            "a compatible thermal descriptor in the firmware.",
            "If BUS/ADDRESS remains, copy the exact thermal topic from ros2 topic list -t. "
            "Multiple cameras require choosing one explicitly.",
            "Read thermal frame waits for a message. If it hangs, press Ctrl+C, check "
            "the publisher and acquisition, then retry.",
            "RViz frame error: run Read thermal frame in Terminal 4, then run RViz there. "
            "The fixed frame must match header.frame_id; no extra TF node is required.",
            "No heatmap: check /sensing/thermal_heatmap has a publisher and the adapter "
            "input matches the camera topic. The RViz display is Marker, not MarkerArray.",
            "Blue/red saturation means temperatures lie outside 15–40 °C. Adjust the "
            "adapter's min_temperature/max_temperature, or enable use_dynamic_range.",
        ],
    )
    hotplug = scenario(
        "distance-hotplug",
        "Axiom · plug, unplug, reconnect",
        "Start with the distance sensor unplugged. Keep Axiom powered and USB connected.",
        [
            *startup,
            run("Sensor inventory", 4, "Leave inventory updates running here."),
            step(
                "Plug in the distance sensor",
                None,
                "The device becomes online; its identity-based topics and alias appear.",
                instruction="Attach a supported distance sensor to an Axiom sensor connector.",
                check=dict(kind="range", namespace=root, present=True),
                flow=[dict(kind="action", name="Plug sensor"),
                      dict(kind="node", name=root + "/axiom_bridge_node"),
                      dict(kind="topic", name=root + "/range")],
            ),
            run("Topic list", 2, f"{root}/bus_…/device_…/range and {root}/range appear."),
            run(
                "Distance readings",
                3,
                "Hold a flat target in range. Finite readings should change as it moves.",
            ),
            step(
                "Unplug the sensor",
                None,
                "The inventory changes and echo waits for data. The driver stays running.",
                instruction="Unplug only the sensor; wait at least five seconds.",
                check=dict(kind="range", namespace=root, present=False),
                flow=[dict(kind="action", name="Unplug sensor"),
                      dict(kind="node", name=root + "/axiom_bridge_node"),
                      dict(kind="topic", name="Distance publishers disappear")],
            ),
            step(
                "Check the alias publisher",
                2,
                "Publisher count: 0. A registered subscriber can keep the topic name visible.",
                custom("Topic details", f"ros2 topic info {root}/range --verbose"),
            ),
            step(
                "Reconnect the sensor",
                None,
                "The publisher returns and the same echo resumes. No "
                "new connection or acquisition command.",
                instruction="Reconnect the sensor and move a target in front of it.",
                check=dict(kind="range", namespace=root, present=True),
                flow=[dict(kind="action", name="Reconnect sensor"),
                      dict(kind="node", name=root + "/axiom_bridge_node"),
                      dict(kind="topic", name=root + "/range")],
            ),
        ],
        [stop(3, "Stop distance echo"), stop(4, "Stop inventory echo"), *cleanup],
        sensor_topics("range", "sensor_msgs/msg/Range"),
    )

    rate = next(
        (
            c
            for d in devices
            if d.get("type") == "LSM6DS" and d.get("online") and not d.get("stale")
            for c in d.get("commands", [])
            if c["name"] == "_conf.rate"
        ),
        None,
    )
    rate_path = (
        root + "/" + rate["service"]
        if rate
        else root + "/bus_BUS/device_ADDRESS/commands/set_sample_rate"
    )
    config = scenario(
        "descriptor-config",
        "Axiom · descriptor configuration",
        "LSM6DS IMU with a live _conf.rate descriptor. This example uses its 52/104 Hz values.",
        [
            *startup,
            run("Device descriptors", 3, "Look for actions, allowed values and their units."),
            run("Service list", 2, "The discovered device has a commands/set_sample_rate service."),
            step(
                "Set the IMU sampling rate",
                2,
                "Firmware confirms 52 Hz and its actual polling settings.",
                custom(
                    "Sensor sample rate",
                    f"ros2 service call {rate_path} axiom_interfaces/srv/DeviceCommand "
                    + shlex.quote('{"values": [52.0]}'),
                ),
            ),
            step(
                "Restore 104 Hz",
                2,
                "Firmware confirms 104 Hz. If your original rate "
                "differed, restore that value instead.",
                custom(
                    "Sensor sample rate",
                    f"ros2 service call {rate_path} axiom_interfaces/srv/DeviceCommand "
                    + shlex.quote('{"values": [104.0]}'),
                ),
            ),
        ],
        [stop(3, "Stop descriptor echo"), *cleanup],
        troubleshooting=[
            "Replace BUS/ADDRESS with the live service path if placeholders are shown.",
            "Use a value from the descriptor map. Other sensors "
            "can have different supported rates.",
        ],
    )
    marty = scenario(
        "marty",
        "Marty · connection & status",
        "Marty over USB or Wi-Fi.",
        [
            run("Marty driver", 1, "Driver running, robot disconnected."),
            run("Connect Marty", 2, "Connected; telemetry starts, no motion is requested."),
            run("Marty status", 3, "Connection and telemetry status."),
        ],
        [stop(3), run("Disconnect Marty", 2, "Robot disconnected."), stop(1)],
    )
    combined = scenario(
        "dual-accelerometers",
        "Axiom + Marty · accelerometers",
        "Axiom with LSM6DS and a connected Marty. No movement commands.",
        [
            run("Axiom driver", 1, "Axiom driver running, disconnected."),
            run("Marty driver", 2, "Marty driver running, disconnected."),
            run("Connect Axiom", 3, "Axiom connected."),
            run("Start Axiom acquisition", 3, "Axiom sensor delivery active."),
            run("Connect Marty", 3, "Marty connected; telemetry active."),
            run("Accelerometer readings", 3, "Axiom acceleration in m/s²."),
            run("Marty accelerometer readings", 4, "Marty acceleration in m/s²."),
            stop(3),
            stop(4),
            run(
                "Dual accelerometer adapter", 3, "Both inputs become labelled acceleration arrows."
            ),
            run(
                "Dual accelerometer RViz",
                4,
                "Fixed Frame accelerometer_view; teal Axiom, orange Marty.",
            ),
        ],
        [
            stop(4),
            stop(3),
            run("Stop Axiom acquisition", 3, "Axiom delivery stopped."),
            run("Disconnect Axiom", 3, "Axiom disconnected."),
            run("Disconnect Marty", 3, "Marty disconnected."),
            stop(2),
            stop(1),
        ],
        sensor_topics("imu/data_raw", "sensor_msgs/msg/Imu"),
    )
    multiple_steps = [
        run(
            "Configure USB + Wi-Fi Axioms", 2, "~/usb_wifi_axioms.yaml is written; no nodes start."
        ),
        run(
            "USB + Wi-Fi Axiom drivers", 1,
            "Both drivers connect automatically and request sensor data at 20 Hz. "
            "Wait for sensor topics to appear before continuing.",
        ),
    ]
    multiple_cleanup = [stop(4, "Close RViz"), stop(3, "Stop the accelerometer adapter")]
    for name in ("front", "rear"):
        ns = "/axiom/" + name
        multiple_cleanup += [
            step(
                "Stop acquisition on " + name,
                2,
                "Firmware delivery stops on " + ns + ".",
                custom(
                    "Stop Axiom acquisition",
                    f"ros2 service call {ns}/publish_data_subscription "
                    "axiom_interfaces/srv/PublishedDataSubscription "
                    + shlex.quote('{"rate_hz": 0.0}'),
                ),
            ),
            step(
                "Disconnect " + name,
                2,
                ns + " is disconnected.",
                custom(
                    "Disconnect Axiom",
                    f"ros2 service call {ns}/disconnect axiom_interfaces/srv/Disconnect "
                    + shlex.quote('{}'),
                ),
            ),
        ]
    multiple = scenario(
        "multiple-axioms",
        "Two Axioms · USB + Wi-Fi + RViz",
        "Two different boards: front on USB; rear powered and connected to Wi-Fi at "
        "192.168.1.11. Both need an LSM6DS for the accelerometer steps. "
        "This scenario enables auto_connect and autosub. "
        "Start from a fresh session with no other driver using either board.",
        [
            *multiple_steps,
            run(
                "Topic list",
                2,
                "Distinct /axiom/front and /axiom/rear topics, even for identical sensors.",
            ),
            *[
                step(
                    connection + " accelerometer readings",
                    terminal,
                    "Acceleration x/y/z in m/s² from /axiom/" + name + ".",
                    custom(
                        "Accelerometer readings",
                        f"ros2 topic echo /axiom/{name}/imu/data_raw sensor_msgs/msg/Imu "
                        "--field linear_acceleration --qos-reliability best_effort",
                    ),
                )
                for name, connection, terminal in (("front", "USB", 3), ("rear", "Wi-Fi", 4))
            ],
            stop(3, "Free Terminal 3 for the adapter"),
            stop(4, "Free Terminal 4 for RViz"),
            run(
                "Two Axiom accelerometer adapter", 3,
                "Both IMU streams become labelled acceleration arrows.",
            ),
            run(
                "Two Axiom RViz", 4,
                "Fixed Frame accelerometer_view. Teal Axiom USB and orange Axiom Wi-Fi "
                "arrows respond independently when each board is tilted.",
            ),
        ],
        [*multiple_cleanup, stop(1, "Stop both drivers")],
        sorted(
            t["name"] for t in graph.get("topics", [])
            if t["name"] in ("/axiom/front/imu/data_raw", "/axiom/rear/imu/data_raw")
            and "sensor_msgs/msg/Imu" in t.get("types", []) and t.get("publishers")
        ),
        troubleshooting=[
            "Native Linux: before creating the configuration, export AXIOM_ROS_SERIAL_PORT "
            "with the USB board's path, preferably /dev/serial/by-id/….",
            "Mac: the front board uses the workstation's USB relay. Keep the original board "
            "on its selected USB port; keep the second board powered for Wi-Fi.",
            "If the Wi-Fi address changes, export AXIOM_WIFI_IP with the new IP in Terminal 2 "
            "before creating the configuration. The workstation must reach that network.",
            "Check ~/usb_wifi_axioms.yaml before launching. USB and Wi-Fi must refer to "
            "different physical boards.",
            "If an IMU alias is absent, check the board's /devices inventory and acquisition. "
            "Use its identity-based topic when multiple IMUs match.",
            "If startup connection fails, call that board's /connect service or restart the "
            "drivers when the board is ready. Automatic reconnection remains disabled.",
            "The launch file rejects duplicate namespaces, frame IDs and connections.",
        ],
    )
    return [hotplug, accel, thermal, distance, config, combined, multiple, marty]
