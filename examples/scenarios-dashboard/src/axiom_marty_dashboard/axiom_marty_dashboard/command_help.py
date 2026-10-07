"""Teaching notes for the guide's console commands, using their actual argument values."""

import json
import shlex


DESCRIPTIONS = {
    "Axiom driver": "Starts the Axiom ROS node and its device services. It stays in the foreground "
    "until Ctrl+C. These settings leave connection, reconnection and firmware acquisition manual.",
    "Marty driver": "Starts the Marty ROS node, including connection services, status topics and "
    "the motion action server. It stays in the foreground until Ctrl+C; connect separately.",
    "RViz marker adapter": "Starts a ROS node that converts sensor measurements into RViz markers "
    "and transforms. It subscribes to sensor data; it does not start acquisition or launch RViz.",
    "RViz": "Opens native RViz with the project's sensor display configuration. Its displays "
    "subscribe to visualization topics; the marker adapter and data publishers must be running.",
    "Thermal grid readings": "Subscribes to one live ThermalGrid message, prints it and exits. "
    "An AMG8833 produces an 8×8 row-major array of 64 pixel temperatures in °C. "
    "Check width, height and header.frame_id before visualizing it.",
    "Read thermal frame": "Reads header.frame_id from one thermal message and stores it in "
    "THERMAL_FRAME in this terminal. RViz uses that frame directly, so no mounting TF is needed. "
    "It waits for live data; it does not connect Axiom or start acquisition.",
    "Thermal heatmap adapter": "Subscribes to ThermalGrid and publishes a coloured CUBE_LIST "
    "Marker at /sensing/thermal_heatmap. Each square represents one measured pixel. "
    "Temperature labels in °C are published on /sensing/thermal_heatmap_labels. "
    "The fixed scale maps 15 °C to blue and 40 °C to red; values outside it use the end colours. "
    "It does not connect, configure or move the device.",
    "Thermal camera RViz": "Opens RViz with a top-down thermal Marker display. The heatmap "
    "adapter must be running. The fixed frame comes from THERMAL_FRAME in this terminal. "
    "If that variable is empty or unset, the shell stops with instructions to read it first. "
    "Colours show measured pixel temperatures; this is not a visible-light camera image.",
    "Dual accelerometer adapter": "Starts a read-only node subscribing to the chosen Axiom IMU "
    "topic and Marty's accelerometer topic. It publishes two labelled acceleration arrows for "
    "RViz, removing each arrow when its readings are invalid or stale. It does not connect "
    "devices, request acquisition or send movements. No dashboard is required.",
    "Dual accelerometer RViz": "Opens native RViz with the two-accelerometer display. Axiom and "
    "Marty have separate display origins; these are not measured mounting transforms. The "
    "arrows show acceleration including gravity, not estimated orientation.",
    "Connect Axiom": "Asks the running Axiom driver to open its device connection. A successful "
    "connection does not start firmware acquisition with the manual driver settings.",
    "Connect Marty": "Asks the running Marty driver to connect using its configured transport "
    "and locator. The response reports success or a connection error.",
    "Disconnect Axiom": "Closes the Axiom driver's device connection. The ROS node stays running; "
    "connect and request acquisition again when ready.",
    "Disconnect Marty": "Closes the Marty driver's device connection while leaving its ROS node "
    "running. Use Connect Marty to open it again.",
    "Start Axiom acquisition": "Requests periodic sensor packets from Axiom's firmware. The driver "
    "decodes them and publishes ROS topics. Firmware delivery rate and each sensor's sample rate "
    "are separate settings; this service call is also separate from a ROS topic subscription.",
    "Stop Axiom acquisition": "Stops firmware delivery of sensor packets without disconnecting "
    "Axiom. Existing ROS subscribers stay registered but receive no new sensor measurements.",
    "Marty stop": "Requests an acknowledged stop directly from the Marty driver.",
    "Axiom connection state": "Queries the Axiom driver's current connection state without "
    "connecting or changing acquisition. The service response contains its state and details.",
    "Ping Axiom": "Sends a firmware version request over Axiom's active connection and reports "
    "round-trip time in milliseconds. This is a firmware request, not an ICMP network ping.",
    "Sensor sample rate": "Changes the selected device's firmware sampling rate. The response "
    "reports the applied rate and polling settings. This does not replace the separate "
    "acquisition service that controls packet delivery to ROS.",
    "Axiom REST request": "Sends a RICREST URL request through the active Axiom connection and "
    "returns raw firmware JSON. This example reads the firmware version.",
    "Walk one step": "Sends a single walking goal to Marty's motion action server. The driver "
    "reports feedback and a final result; only one goal is admitted at a time.",
    "Dance": "Sends a dance goal to Marty's motion action server and displays its feedback and "
    "final result. Marty must be connected and ready to accept a goal.",
    "Kick": "Sends a kick goal to Marty's motion action server and displays its feedback and "
    "final result. Marty must be connected and ready to accept a goal.",
    "Stand": "Sends a stand-straight goal to Marty's motion action server and displays its "
    "feedback and final result.",
    "Move eyebrows": "Moves Marty's eyebrow servo to the requested angle through the motion "
    "action server, with feedback and a final result.",
    "Node list": "Lists nodes discovered in this ROS domain. It is a graph inspection command; "
    "it does not start any project nodes.",
    "Node details": "Shows a discovered node's publishers, subscriptions, services and actions. "
    "The named node must already be running.",
    "Topic details": "Shows a topic's discovered publishers, subscribers and QoS. This inspects "
    "the ROS graph without subscribing to measurements or starting a publisher.",
    "Accelerometer readings": "Creates a ROS subscriber and prints only linear_acceleration "
    "from the IMU message until Ctrl+C. Its x, y and z components are in m/s² and include gravity. "
    "Firmware acquisition must already be active.",
    "Marty accelerometer readings": "Creates a ROS subscriber and prints Marty's x/y/z "
    "acceleration in m/s², including gravity, until Ctrl+C. The driver requests firmware "
    "telemetry when you connect Marty; this command subscribes to its ROS messages. "
    "Marty does not supply orientation or angular velocity in this IMU topic.",
    "Topic list": "Lists discovered ROS topics and their message types. Discovery alone does "
    "not mean messages are currently being delivered.",
    "Service list": "Lists discovered ROS services and their request/response interface types. "
    "It does not call any services.",
    "Action list": "Lists discovered ROS actions and their interface types. It does not send "
    "any motion goals.",
    "Sensor inventory": "Subscribes to and prints Axiom's sensor inventory until Ctrl+C. The "
    "durability setting also requests the last retained inventory from a compatible publisher.",
    "Marty status": "Subscribes to and prints Marty driver status until Ctrl+C, including the "
    "last retained status from a compatible publisher.",
    "Parameters": "Prints the running node's parameter values as YAML. It does not change them; "
    "use ros2 param set for a writable parameter.",
    "Motion interface": "Prints the Motion action definition: goal fields, result fields, "
    "feedback fields and command constants. It can be read without connecting Marty.",
    "Record telemetry": "Starts a rosbag recorder that subscribes to the listed topics and "
    "writes received messages to a new recording directory in the current working directory. "
    "Ctrl+C closes the recording; it does not start missing publishers.",
    "Distance readings": "Creates a ROS subscription and prints range messages until Ctrl+C. "
    "Distances in sensor_msgs/Range are in metres; acquisition must already be active.",
    "Distance frequency": "Subscribes to the range topic and estimates its received message "
    "frequency until Ctrl+C. This measures delivery at this subscriber, not the firmware's "
    "configured sensor sampling rate.",
    "Browser guide": "Starts the optional teaching dashboard. It observes inventory and the ROS "
    "graph and serves the guide on AXIOM_DASHBOARD_PORT (default 8083). "
    "It does not start driver nodes, connect "
    "devices or request sensor acquisition.",
    "Topic echo": "Creates a ROS subscription and prints received messages until Ctrl+C. Replace "
    "BUS and ADDRESS with an actual device identity from /axiom/devices. This command does not "
    "start the publisher or request firmware acquisition.",
    "Multiple Axiom drivers": "Starts one independent ROS driver per configured board. Each "
    "has its own connection, namespace and frame prefix; connection and acquisition remain manual.",
    "Configure USB + Wi-Fi Axioms": "Writes ~/usb_wifi_axioms.yaml with two independent board "
    "connections and optional sensor aliases. It replaces this example file when run again. "
    "It does not start ROS nodes or connect devices. Edit the values before launching if needed.",
    "USB + Wi-Fi Axiom drivers": "Starts /axiom/front for the USB board and /axiom/rear for the "
    "Wi-Fi board using ~/usb_wifi_axioms.yaml. With this scenario's configuration, both "
    "connect automatically and request firmware data at 20 Hz. Keep this terminal running.",
    "Two Axiom accelerometer adapter": "Subscribes to both Axiom IMU topics and publishes "
    "labelled acceleration arrows for RViz. Teal is USB; orange is Wi-Fi. The display origins "
    "are a layout, not measured mounting transforms. It does not connect or configure devices.",
    "Two Axiom RViz": "Opens native RViz with the two-accelerometer display. The adapter "
    "must be running. The arrows show acceleration including gravity, not estimated orientation.",
    "Device descriptors": "Prints live firmware descriptors, including measurement fields, "
    "commands and their allowed arguments. It does not configure the sensors.",
    "Start from scratch": "Requests a reset of this learning workstation. It stops session "
    "processes and reopens the guide with four empty tmux panes. Start nodes, connect devices "
    "and request acquisition again manually. Project and build files remain intact.",
}

PARAMETERS = {
    "boards_file": "YAML board configuration shared with the guide. The namespace selects "
    "one board in the single-driver launch; the multi-driver launch starts every entry. "
    "Explicit launch arguments override the selected board's parameters.",
    "transport": "Axiom transport: serial for a Linux USB device, or ws for a WebSocket "
    "connection. Uses AXIOM_ROS_TRANSPORT when set, otherwise serial.",
    "device_uri": "Axiom WebSocket address. Uses AXIOM_ROS_URI when set, otherwise the shown "
    "Wi-Fi URL. The Mac workstation supplies its USB relay URL through this environment variable.",
    "serial.port": "Linux serial device path. Uses AXIOM_ROS_SERIAL_PORT when set, otherwise "
    "/dev/ttyACM0; used when transport is serial.",
    "auto_connect": "false leaves the device disconnected until its connect service is called.",
    "auto_reconnect": "false requires an explicit connect call after a connection is lost.",
    "autosub": "false leaves firmware acquisition off until publish_data_subscription is called.",
    "method": "Marty transport, such as usb or wifi. Uses MARTY_ROS_METHOD when set, "
    "otherwise usb.",
    "locator": "Marty's serial path or Wi-Fi IP address, according to method. Uses "
    "MARTY_ROS_LOCATOR when set, otherwise /dev/ttyUSB0.",
    "wifi_port": "Marty's Wi-Fi port. Uses MARTY_ROS_WIFI_PORT when set, otherwise 80; "
    "used when method is wifi.",
    "axiom_topic": "Full Axiom sensor_msgs/Imu topic path, including the board namespace.",
    "axiom_namespace": "Board namespace whose inventory and sensor data should be visualized.",
    "marty_topic": "Second sensor_msgs/Imu input, normally /marty/imu/data_raw. "
    "The two-Axiom scenario uses /axiom/rear/imu/data_raw here; no Marty is needed.",
    "axiom_label": "Display label for the first IMU input.",
    "marty_label": "Display label for the second IMU input.",
    "input_topic": "Full discovered ThermalGrid input topic, including the Axiom namespace "
    "and sensor identity. Replace BUS/ADDRESS placeholders with the live topic.",
    "output_topic": "Marker output topic. thermal_heatmap resolves to /sensing/thermal_heatmap "
    "under the chosen node namespace.",
    "use_dynamic_range": "false keeps the temperature colour scale fixed between frames. "
    "true rescales each frame to its own minimum and maximum.",
    "min_temperature": "Cool end of the fixed colour scale, in °C.",
    "max_temperature": "Warm end of the fixed colour scale, in °C; must exceed the minimum.",
}

FIELDS = {
    "device_uri": "Empty uses the driver's configured address or serial port. Set a nonempty "
    "value to override the target for this connection; transport is configured at node startup.",
    "rate_hz": "Firmware packet delivery rate in hertz. 20.0 requests delivery at 20 Hz; "
    "0.0 unsubscribes. This is not an individual sensor's sampling rate.",
    "payload_size": "Optional padding bytes added to the firmware version request. 0 sends "
    "no padding; this is not an echo payload.",
    "bus": "Bus identifier from /axiom/devices, with the bus_ prefix removed.",
    "address": "Device address from the inventory, hexadecimal without 0x or the device_ prefix. "
    "For example, device_129 uses the string 129 as hexadecimal, not decimal.",
    "sample_rate_hz": "Requested sensor sampling rate in hertz. The firmware may apply a "
    "supported rate; read sample_rate_hz in the response for the actual rate.",
    "url_path": "Firmware RICREST path without a leading slash. v reads the version; other "
    "paths can change device configuration depending on the firmware API.",
    "timeout": "Response timeout in seconds. 2.0 waits up to two seconds; 0 uses the node default.",
    "ws_pcol": "Empty keeps the session's configured framing. A nonempty RICSerial or RICFrame "
    "value must match the current session; this request cannot change its framing.",
    "num_steps": "Number of walking steps, 1–10. An explicit left/right starting foot requires "
    "one step; auto permits multiple steps.",
    "side": "For walking: auto, left or right starting foot. For dance and kick: left or right.",
    "step_length_mm": "Walking step length in millimetres, −50 to 50. Here 20 requests a "
    "20 mm step; zero allows turning in place.",
    "turn_degrees": "Walking turn angle in degrees, −100 to 100. Zero requests no turn.",
    "move_time_ms": "Movement duration in milliseconds, 100–10000. For walking this applies "
    "to each step; here 1200 is 1.2 seconds.",
    "joint_id": "Firmware servo identifier, 0–8. Servo 8 controls Marty's eyebrows.",
    "position_degrees": "Target joint angle in degrees, −90 to 90. Here zero is the neutral angle.",
}


def explain(title, command):
    """Document each displayed token without executing or evaluating shell expressions."""
    tokens = shlex.split(command)
    arguments = []

    def arg(name, description):
        arguments.append({"name": name, "description": description})

    family = tokens[:3]
    if title == "Read thermal frame":
        arg("THERMAL_FRAME=$(…)", "Captures this command's output into a shell variable in "
            "the current terminal. Use the same terminal for the subsequent RViz command.")
        arg(command.split("ros2 topic echo ", 1)[1].split(" ", 1)[0],
            "Discovered thermal topic. Replace BUS/ADDRESS if placeholders remain.")
        arg("axiom_interfaces/msg/ThermalGrid", "Message type published by the thermal camera.")
        arg("--field header.frame_id", "Prints the sensor frame name rather than its pixels.")
        arg("--qos-reliability best_effort", "Matches the sensor publisher's QoS.")
        arg("--once", "Reads one message and removes the temporary subscription. "
            "Ctrl+C cancels the wait if no data is arriving.")
        arg("sed -n '1p'", "Keeps the frame name and removes ROS echo's YAML separator.")
        arg('printf \'%s\\n\' "$THERMAL_FRAME"', "Prints the stored frame for you to check.")
    elif tokens[0] == "cat" and title == "Configure USB + Wi-Fi Axioms":
        arg('> "$HOME/usb_wifi_axioms.yaml"', "Writes the configuration file in your Linux home "
            "directory. Re-running the command replaces this file.")
        arg("<<EOF … EOF", "A shell here-document supplies the YAML. Paste the whole block, "
            "including the final EOF line; environment variables are expanded by the shell.")
        arg("axiom/front", "Namespace for the USB board. AXIOM_ROS_TRANSPORT and AXIOM_ROS_URI "
            "select the USB relay in the Mac workstation. Native Linux defaults to serial; "
            "AXIOM_ROS_SERIAL_PORT defaults to /dev/ttyACM0.")
        arg("axiom/rear", "Namespace for the Wi-Fi board. Connects directly to "
            "ws://192.168.1.11/ws, or the address supplied in AXIOM_WIFI_IP.")
        arg("auto_connect: true / autosub: true", "Each driver connects and requests sensor "
            "data automatically when launched. No separate connect or acquisition call is needed.")
        arg("publish_rate_hz: 20.0", "Requests firmware packet delivery at 20 Hz. "
            "This is separate from each sensor's sampling rate.")
        arg("auto_reconnect: false", "A failed or lost connection requires an explicit "
            "connect service call or a driver restart.")
        arg("topic_aliases", "Adds imu/data_raw for one matching LSM6DS and range for one "
            "matching VL53L4CD under each board's namespace. Identity-based topics also remain.")
    elif family == ["ros2", "service", "call"]:
        arg(tokens[3], "Service name: the endpoint that receives this request. Its node must run.")
        arg(tokens[4], "Service type: defines request and response fields; must match the service.")
        fields = json.loads(tokens[5])
        arg(
            "REQUEST",
            "The quoted JSON object is also valid YAML, which ROS uses to construct the "
            "typed request. {} is an empty request."
            if not fields
            else "The quoted JSON object is valid YAML. ROS "
            "constructs a typed request from its fields.",
        )
        for key, value in fields.items():
            arg(
                f"{key}: {json.dumps(value)}",
                FIELDS.get(
                    key,
                    "Numeric values in descriptor order and units; [] for a no-argument command.",
                ),
            )
    elif family == ["ros2", "action", "send_goal"]:
        arg(
            tokens[3],
            "Action name: Marty's motion endpoint. An action has a goal, ongoing "
            "feedback and a final result, rather than a single service response.",
        )
        arg(tokens[4], "Action type: defines the goal, result and feedback fields.")
        arg(
            "GOAL",
            "The quoted JSON/YAML object provides goal fields. Omitted fields keep "
            "their ROS message defaults; unused fields are ignored for this command.",
        )
        for key, value in json.loads(tokens[5]).items():
            detail = (
                "Movement selector: 0 walk, 1 dance, 2 kick, 3 stand, 4 move joint."
                if key == "command"
                else FIELDS[key]
            )
            arg(f"{key}: {json.dumps(value)}", detail)
        arg("--feedback", "Prints action feedback while the goal runs, then the final result.")
    elif tokens[:2] == ["ros2", "run"]:
        arg(tokens[2], "Package containing the executable. The ROS workspace must be sourced.")
        arg(tokens[3], "Executable to start. Keep this terminal open; Ctrl+C stops this process.")
        for index in range(4, len(tokens)):
            token = tokens[index]
            if token == "--ros-args":
                arg(token, "Starts ROS arguments, including remappings and node parameters.")
            elif token == "-r":
                arg(
                    "-r " + tokens[index + 1],
                    "Remaps __ns, the node namespace. Relative topics "
                    "and services are resolved beneath this namespace.",
                )
            elif token == "-p":
                value = tokens[index + 1]
                arg(
                    "-p " + value,
                    PARAMETERS.get(
                        value.split(":=", 1)[0],
                        "Node parameter; use ros2 param describe for its contract.",
                    ),
                )
            elif token == "-d":
                arg("-d " + tokens[index + 1], "RViz display configuration file.")
            elif token == "-f":
                arg("-f " + tokens[index + 1], "RViz Fixed Frame override. The shell expands "
                    "THERMAL_FRAME set by Read thermal frame in this terminal. The :? check "
                    "stops before RViz launches when the variable is empty or unset.")
    elif tokens[:2] == ["ros2", "launch"]:
        arg(tokens[2], "Package containing the launch file.")
        arg(tokens[3], "Launch description. Keep this terminal open; Ctrl+C stops its nodes.")
        for token in tokens[4:]:
            key = token.split(":=", 1)[0]
            arg(
                token,
                PARAMETERS.get(
                    key,
                    {
                        "namespace": "ROS namespace for this board; relative "
                        "topics and services live here.",
                        "params_file": "YAML driver parameters, including optional topic aliases.",
                        "boards_file": "YAML mapping of board namespaces to "
                        "connections and parameters.",
                    }.get(key, "Launch argument override."),
                ),
            )
    elif family in (["ros2", "node", "info"], ["ros2", "param", "dump"]):
        arg(tokens[3], "Fully qualified name of the node to inspect, including its namespace.")
    elif family == ["ros2", "interface", "show"]:
        arg(tokens[3], "Interface identifier: package/action/name for this action definition.")
    elif family == ["ros2", "topic", "echo"]:
        arg(tokens[3], "Topic name to subscribe to. Echo creates a subscriber, not a publisher.")
        index = 4
        if index < len(tokens) and not tokens[index].startswith("--"):
            arg(tokens[index], "Message type to subscribe with. Must match the topic publisher.")
            index += 1
        details = {
            "--qos-durability": "Requests retained messages from a transient-local publisher; "
            "normal live messages are received too.",
            "--qos-reliability": "Uses best-effort delivery to match the sensor publisher. "
            "Packets can be dropped rather than retried; a reliable subscriber cannot match "
            "a best-effort publisher.",
            "--field": "Prints only this message field. linear_acceleration contains x/y/z in "
            "m/s²; range is distance in metres. The subscriber still receives the whole message.",
        }
        while index < len(tokens):
            flag = tokens[index]
            if flag == "--once":
                arg(flag, "Prints the first message, then exits and removes this subscriber.")
                index += 1
            else:
                arg(flag + " " + tokens[index + 1], details[flag])
                index += 2
    elif family == ["ros2", "topic", "info"]:
        arg(
            tokens[3],
            "Topic to inspect. The shell expands a variable such as $IMU_TOPIC using "
            "the value exported in this terminal.",
        )
        if "--verbose" in tokens:
            arg("--verbose", "Includes endpoint node names, message types and QoS settings.")
    elif family == ["ros2", "topic", "hz"]:
        arg(tokens[3], "Topic whose received message frequency will be measured.")
    elif family == ["ros2", "bag", "record"]:
        for topic in tokens[3:]:
            arg(topic, "Topic to subscribe to and record. Only received messages are written.")
    elif family[-1] == "list":
        if "-t" in tokens:
            arg("-t", "Shows each discovered interface's type alongside its name.")
        else:
            arg("No additional arguments", "Lists all discovered nodes in the current ROS domain.")
        if "--no-daemon" in tokens:
            arg(
                "--no-daemon",
                "Uses discovery in this CLI process without starting or consulting "
                "the background ROS CLI daemon.",
            )
    elif tokens[0] == "python3" and tokens[-1] == "request":
        arg("python3", "Runs the workstation adapter with Python 3.")
        arg(tokens[1], "Optional reset script; this path is inside the Linux workstation.")
        arg(
            "request",
            "Queues one reset with the host supervisor. This terminal will close when "
            "the workstation restarts; no ROS commands are replayed.",
        )
    else:
        raise ValueError("Missing argument documentation: " + command)
    description = DESCRIPTIONS.get(
        title, "Run this command in the indicated console. It is never executed by the guide."
    )
    return {"description": description, "arguments": arguments}
