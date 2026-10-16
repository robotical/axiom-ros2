# axiom_debug_tools

Small ROS subscribers for inspecting host-driver measurements. Complete the
[host setup](../../README.md), connect and start acquisition first. These tools
subscribe to ROS topics; they do not open Axiom connections or enable firmware
delivery. They are included in the core build.

## Pick actual topics

In a prepared terminal at the repository root:

```bash
source scripts/setup_env.sh
ros2 topic list -t --no-daemon
```

Replace the placeholders below with full discovered topics. Set variables in
each terminal that uses them. All monitors use best-effort QoS and the same ROS
domain/middleware as the driver.

| Executable | Parameters | Output |
|---|---|---|
| `axiom_topic_sniff` | Required `topic` and `type`; optional `depth` (10) | JSON message view and an approximate received rate |
| `axiom_imu_monitor` | `topic`; built-in relative default `lsm6ds_b1_6a/data_raw` | Acceleration, gyro, running gyro average, approximate rate and simple sanity warnings |
| `axiom_range_monitor` | `topic`; built-in relative default `vl53l4cd_b1_29/range` | Scalar range in metres, approximate rate and min/max checks |
| `axiom_env_monitor` | `temp_topic` and `hum_topic`; relative defaults under `aht20_b1_38` | Temperature °C, humidity %RH and approximate rates |

Built-in defaults are example identities, not automatic sensor discovery. Use
explicit absolute topics for your board, or remap the node namespace only when
the relative defaults match your actual sensors.

## IMU and scalar range

Run each monitor in its own terminal:

```bash
IMU_TOPIC='PASTE_DISCOVERED_IMU_TOPIC_HERE'
ros2 run axiom_debug_tools axiom_imu_monitor --ros-args -p topic:="$IMU_TOPIC"
```

```bash
RANGE_TOPIC='PASTE_DISCOVERED_SCALAR_RANGE_TOPIC_HERE'
ros2 run axiom_debug_tools axiom_range_monitor --ros-args -p topic:="$RANGE_TOPIC"
```

The range monitor expects `sensor_msgs/msg/Range`, not a multizone Image.
IMU acceleration includes gravity in m/s² and gyro values are rad/s. The running
gyro average is a diagnostic, not a calibration or bias correction. The six-axis
message has no fused orientation.

## Environmental or generic messages

```bash
TEMP_TOPIC='PASTE_DISCOVERED_TEMPERATURE_TOPIC_HERE'
HUM_TOPIC='PASTE_DISCOVERED_HUMIDITY_TOPIC_HERE'
ros2 run axiom_debug_tools axiom_env_monitor --ros-args \
  -p temp_topic:="$TEMP_TOPIC" -p hum_topic:="$HUM_TOPIC"
```

```bash
SENSOR_TOPIC='PASTE_DISCOVERED_SENSOR_TOPIC_HERE'
SENSOR_TYPE='PASTE_DISCOVERED_ROS_MESSAGE_TYPE_HERE'
ros2 run axiom_debug_tools axiom_topic_sniff --ros-args \
  -p topic:="$SENSOR_TOPIC" -p type:="$SENSOR_TYPE"
```

Use the type shown by `ros2 topic list -t`, such as `sensor_msgs/msg/Imu`.
Per-message rates are receipt observations and can vary with batching and scheduling;
use `ros2 topic hz` for a rolling received-rate check. Stop a monitor with Ctrl+C;
acquisition continues until stopped through the driver.
