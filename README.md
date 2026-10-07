# Axiom ROS 2

Robotical's Axiom ROS 2 driver and tools.

Tested stack: Ubuntu 24.04, ROS 2 Jazzy. Transports: USB serial and framed
WebSocket (`/ws`). One driver instance per Axiom.

## Build on Linux

Requires ROS 2 Jazzy, `rosdep` and `colcon`. Run from the repository root:

```bash
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --base-paths src --symlink-install
source install/setup.bash
```

Source ROS and `install/setup.bash` in each ROS terminal.

## Optional scenarios dashboard

The console guide, ROS graph, scenarios and RViz examples are in
[examples/scenarios-dashboard](examples/scenarios-dashboard/README.md).
Build them alongside the driver from this repository:

```bash
rosdep install --from-paths src examples/scenarios-dashboard/src --ignore-src -r -y
colcon build --base-paths src examples/scenarios-dashboard/src --symlink-install
source install/setup.bash
ros2 run axiom_marty_dashboard dashboard
```

Open http://127.0.0.1:8083. The dashboard observes ROS state and provides commands
to run in the console. Drivers, acquisition and RViz work independently of it.
`COLCON_IGNORE` excludes the example from default recursive builds; specifying
its `src` directory includes it. Marty packages are needed only for Marty scenarios.

## Connect a board

USB, Terminal 1:

```bash
ros2 launch axiom_bringup bringup.launch.py \
  transport:=serial serial.port:=/dev/ttyACM0
```

Replace the serial path as needed; prefer `/dev/serial/by-id/…`. Serial device
permissions must allow access from the account running the driver.

Wi-Fi, Terminal 1 (replace the IP):

```bash
ros2 launch axiom_bringup bringup.launch.py \
  transport:=ws device_uri:=ws://192.168.1.11/ws
```

Defaults: namespace `axiom`; `auto_connect`, `autosub` and `auto_reconnect` are
false. `enable_plotter`, `enable_thermal` and `enable_rqt` are also false.

Connection and acquisition, Terminal 2:

```bash
ros2 service call /axiom/connect axiom_interfaces/srv/Connect '{device_uri: ""}'
ros2 service call /axiom/publish_data_subscription axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 20.0}'
ros2 topic list -t --no-daemon
```

Inventory and IMU inspection. Run the echoes separately and use the topic path
from the inventory or topic list:

```bash
ros2 topic echo /axiom/devices --qos-durability transient_local
ros2 topic echo /axiom/bus_1/device_76a/imu/data_raw --qos-reliability best_effort
```

Ctrl+C stops an echo subscriber; acquisition continues. Stop acquisition with
rate zero, then disconnect:

```bash
ros2 service call /axiom/publish_data_subscription axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 0.0}'
ros2 service call /axiom/disconnect axiom_interfaces/srv/Disconnect '{}'
```

Automatic startup: `auto_connect:=true autosub:=true`. Connection retries:
`auto_reconnect:=true`. These are independent startup parameters.

## Sensor discovery and hot plugging

During acquisition, firmware descriptors drive sensor discovery, decoding and
creation of ROS topics and configuration/output services. Unplug retires the
device's publishers and services; reconnect recreates them without a driver restart.

`topic_aliases` only adds names such as `/axiom/imu/data_raw`; it is not a sensor
inventory or support list. Identity-based topics remain available. New standard
descriptor profiles require no per-sensor YAML entry. Unsupported custom binary
formats or ROS message mappings require driver changes.

Topic addresses are normalized hexadecimal extended firmware addresses. Use the
inventory paths, not assumed physical I2C addresses. Services: `ros2 service list -t`.
Descriptors: `/axiom/device_metadata`.

## Multiple Axioms

Each board has a separate driver, namespace, connection and frame prefix. Copy
the example and edit the endpoints:

```bash
cp "$(ros2 pkg prefix --share axiom_driver)/config/two_axioms.yaml" ./axioms.yaml
```

USB + Wi-Fi configuration with automatic acquisition:

```yaml
axioms:
  axiom/front:
    transport: serial
    serial.port: /dev/ttyACM0
    auto_connect: true
    autosub: true
    publish_rate_hz: 20.0
  axiom/rear:
    transport: ws
    device_uri: ws://192.168.1.11/ws
    auto_connect: true
    autosub: true
    publish_rate_hz: 20.0
```

Save as `axioms.yaml` and launch:

```bash
ros2 launch axiom_driver multi_axiom.launch.py boards_file:="$PWD/axioms.yaml"
```

Topics and services are scoped under `/axiom/front` and `/axiom/rear`. Sensor
addresses are independent across boards. Duplicate namespaces, frame prefixes and
endpoints are rejected. Without the automatic startup flags, call each board's
connection and acquisition services separately.

## Architecture

```mermaid
flowchart LR
    FW["Axiom firmware: polling + FIFO"] --> S["Session: framed WS or serial"]
    S --> Q["Bounded receive queue"]
    Q --> P["Pipeline: registry + metadata + decoding + device time"]
    P --> A["ROS adapters: standard messages + DeviceSample"]
    A --> DDS["DDS: multiple consumers / rosbag"]
    ROS["ROS services"] --> S
    ROS --> P
    S --> FW
```

| Package | Responsibility |
|---|---|
| `axiom_driver` | Pure Python firmware client, single ordered decode worker, ROS adapters and services |
| `axiom_interfaces` | Generic timestamped sample and compatibility messages; connection/configuration services |
| `axiom_bringup` | Namespace, parameter file and optional visualization launch |
| `axiom_debug_tools` | IMU/range/environment monitoring |
| `axiom_plotter` | Topic discovery and timestamp-based plot history |
| `axiom_thermal_viz` | ThermalGrid to RViz markers |
| `axiom_shake_detector` | Optional shake-event consumer for teaching examples |

Details: [parameters and ROS interfaces](src/axiom_driver/README.md),
[firmware compatibility](docs/firmware-alignment.md),
[validation](docs/validation.md).

Run one firmware acquisition client per board. Other direct firmware clients
compete for the firmware publication queue. Additional consumers should subscribe
to the ROS topics; they share the driver's DDS output.

## Tests

```bash
colcon test --event-handlers console_direct+
colcon test-result --verbose
```

Tests use WebSocket peers, POSIX virtual serial ports and ROS DDS with
firmware-source fixtures. Hardware checks are recorded in `docs/validation.md`.
