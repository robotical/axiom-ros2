# Scenarios dashboard

Internal Robotical example for Axiom scenarios, RViz adapters and the browser
guide. Marty scenarios use the same workspace. Driver control is through ROS
commands; the guide observes state and displays command examples.

## Native Linux

Stack: ROS 2 Jazzy on Ubuntu 24.04. Run these commands from the `axiom-ros2`
repository root. The dashboard and RViz adapters are included in this clone.

```bash
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src examples/scenarios-dashboard/src --ignore-src -r -y
colcon build --base-paths src examples/scenarios-dashboard/src --symlink-install
source install/setup.bash
```

Optional tmux consoles:

```bash
sudo apt install tmux
bash examples/scenarios-dashboard/scripts/ros_tmux.sh
```

Guide, in a separate terminal:

```bash
ros2 run axiom_marty_dashboard dashboard
```

Guide: http://127.0.0.1:8083. Scenarios, command notes, interface inventory and
current DDS graph. Board selection scopes the commands; the running graph covers
all discovered nodes. Device connection and acquisition are controlled by the drivers.

Scenarios show one expanded step, with Previous/Next navigation and an Expand all
view. Each step pairs its expected result with read-only ROS evidence and a small
relationship diagram. Discovery verifies endpoints, not message delivery or command
execution; confirm those in the console. Command arguments remain under ⓘ, and
setup, shortcuts, troubleshooting and cleanup remain available below the outline.

The **Axiom · thermal camera + RViz** scenario uses one Axiom and an AMG8833
(8×8 pixels). It connects and starts acquisition through explicit console commands,
then reads a `ThermalGrid`, starts `axiom_thermal_viz` and opens the supplied RViz
heatmap. The guide fills in the topic when exactly one camera publisher is discovered;
otherwise choose its identity-based topic from `ros2 topic list -t`. RViz uses the
camera's own frame and a fixed 15–40 °C colour scale. It needs no dashboard at runtime.

## Plug, unplug and reconnect

Terminal 1 (replace the USB path):

```bash
ros2 launch axiom_driver axiom_minimal_launch.py \
  transport:=serial serial.port:=/dev/ttyACM0 \
  params_file:="$(ros2 pkg prefix --share axiom_driver)/config/hotplug.yaml"
```

Terminal 2:

```bash
ros2 service call /axiom/connect axiom_interfaces/srv/Connect '{device_uri: ""}'
ros2 service call /axiom/publish_data_subscription axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 20.0}'
ros2 topic list -t --no-daemon
```

Terminal 3:

```bash
ros2 topic echo /axiom/range sensor_msgs/msg/Range --field range --qos-reliability best_effort
```

Terminal 4:

```bash
ros2 topic echo /axiom/devices --qos-durability transient_local
```

With VL53L4CD attached, the device topic and optional `/axiom/range` alias appear.
Unplug removes the publisher; echo waits. Reconnect resumes data without a driver
restart or another acquisition request. Range is in metres; invalid measurements
are NaN. A subscriber can keep a topic listed after its publisher disappears.
Check publisher count with `ros2 topic info /axiom/range --verbose`.

Firmware must support sensor detection and supply its descriptor. Standard
descriptor profiles need no per-sensor ROS configuration. Unsupported custom
binary formats or ROS message mappings require driver changes.

## Aliases and descriptor services

The driver's normal `axiom.yaml` has no aliases. `hotplug.yaml` adds optional
aliases for LSM6DS and VL53L4CD while preserving identity-based topics. Rules map
an alias to `type`, `source`, and optional string `bus`/`address` selectors. If
multiple devices match, no alias is published until the selection is unambiguous.
Aliases live beneath each board's namespace. Restart the driver to change its
read-only configuration.

Device descriptors create services under:

```text
/axiom/bus_BUS/device_ADDRESS/commands/COMMAND
```

Paths: `ros2 service list -t`. Argument ranges/maps: `/axiom/device_metadata` or
the guide's information dialog. LSM6DS sample-rate example:

```bash
ros2 service call /axiom/bus_1/device_76a/commands/set_sample_rate axiom_interfaces/srv/DeviceCommand '{values: [52.0]}'
ros2 service call /axiom/bus_1/device_76a/commands/set_sample_rate axiom_interfaces/srv/DeviceCommand '{values: [104.0]}'
```

Output-only modules also expose descriptor services. LED commands can include
`brightness`, `pixels` and `off`. Numeric arguments follow descriptor order and units;
`off` uses `{values: []}`. Out-of-range values are rejected before transmission.
Success means firmware acknowledgment, not completion of physical movement.
Commands requiring unsupported custom value formats are not advertised as
callable services. Configuration/output requests use ROS services; Marty's
longer motion operations retain their ROS action interface.

## RViz and Marty

Marty is optional. To use its scenarios, clone `marty-ros2` beside `axiom-ros2`
and include its packages when building from the `axiom-ros2` root:

```bash
rosdep install --from-paths src examples/scenarios-dashboard/src ../marty-ros2/src --ignore-src -r -y
colcon build --base-paths src examples/scenarios-dashboard/src ../marty-ros2/src --symlink-install
source install/setup.bash
```

The single-Axiom and Axiom/Marty scenarios use explicit connection and acquisition
calls. RViz adapters subscribe to ROS measurements and publish markers. Display
origins are a layout, not measured mounting transforms or pose estimates. The guide,
adapters and RViz run independently.

## Multiple Axioms

Copy the example, then edit the endpoints and startup flags before launching:

```bash
cp "$(ros2 pkg prefix --share axiom_driver)/config/two_axioms.yaml" ./axioms.yaml
```

```bash
ros2 launch axiom_driver multi_axiom.launch.py boards_file:="$PWD/axioms.yaml"
```

Each board has its own driver, connection, namespace, registry and frame prefix.
Use stable `/dev/serial/by-id` paths where available. The launch file rejects
reused namespaces, frame IDs and connections. Connect and enable acquisition on
`/axiom/front` and `/axiom/rear` separately. Identical sensor addresses on different
boards do not conflict.

**Two Axioms · USB + Wi-Fi + RViz** writes
`~/usb_wifi_axioms.yaml`: `/axiom/front` uses a Linux USB serial port, and
`/axiom/rear` uses `ws://192.168.1.11/ws`. Run the configuration
step first, then launch. Both drivers use `auto_connect: true`, `autosub: true`
and a delivery rate of 20 Hz. Subscribe to each IMU in the console, stop those
subscribers, then start the two-Axiom adapter and RViz in Terminals 3 and 4.
RViz labels the teal USB and orange Wi-Fi acceleration arrows separately.
Other scenarios retain their manual connection and acquisition steps.
Set `AXIOM_ROS_SERIAL_PORT` before creating the file if the USB
path differs from `/dev/ttyACM0`. Set `AXIOM_WIFI_IP` in that same terminal if the
second board's IP changes. USB and Wi-Fi endpoints must refer to different
physical boards. Keep the Wi-Fi board powered.

## tmux

`examples/scenarios-dashboard/scripts/ros_tmux.sh` opens four consoles in a 2×2 layout.
`Ctrl+b`, then an arrow selects a pane;
`Ctrl+b`, then `d` detaches without stopping commands. Run the script again to
reattach. `Ctrl+C` stops the foreground command in the active pane. Linux terminals
usually paste with `Ctrl+Shift+V`.

Further tmux commands: [tmux guide](https://github.com/tmux/tmux/wiki/Getting-Started).
Checks and hardware observations: [docs/validation.md](docs/validation.md).
