# Sensors and multiple Axioms

Complete the [host-driver setup](../README.md) and leave acquisition running.
The examples use the namespace `/axiom`. Substitute your configured namespace
and the actual discovered sensor identities. `boards.yaml` describes board
connections and optional aliases; sensors do not need to be listed individually.

## Discover topics and commands

In a prepared ROS terminal:

```bash
ros2 topic list -t --no-daemon
ros2 service list -t
ros2 topic echo /axiom/devices --qos-durability transient_local --once
```

| Topic suffix | Type and units |
|---|---|
| `imu/data_raw` | `sensor_msgs/msg/Imu`; acceleration m/s², including gravity, and angular velocity rad/s; no fused orientation |
| `range` | `sensor_msgs/msg/Range`; scalar distance in metres; invalid readings are NaN |
| `range/image` | `sensor_msgs/msg/Image`; supported multizone distance grids, `32FC1` in metres; invalid zones are NaN |
| `temperature` | `sensor_msgs/msg/Temperature`; °C |
| `humidity` | `sensor_msgs/msg/RelativeHumidity`; fraction from 0 to 1 |
| `thermal/grid` | `axiom_interfaces/msg/ThermalGrid`; dimensions and pixel temperatures |
| `thermal/image` | `sensor_msgs/msg/Image`; known Celsius values as `32FC1` for a 2D heatmap |
| `sample` | `axiom_interfaces/msg/DeviceSample`; decoded values, validity and timing |
| `data` | `std_msgs/msg/String`; JSON decoded measurement view |

Identity-based paths contain the firmware bus and normalized hexadecimal device
address. Use the inventory or topic list, rather than deriving an address from a
connector number. Profiles with supported layouts/decoding can supply generic
`sample` and `data` topics. Standard typed topics also need the corresponding ROS
mapping and known units. A Device Library profile does not automatically add support
for a new custom binary decoder; see the [driver contracts](../src/axiom_driver/README.md).

## Sensor hot swapping and board reconnection

With Axiom powered, connected and acquiring, plug in a supported sensor. Its
publishers and descriptor services appear once its metadata is resolved. Unplug
only that sensor, leaving Axiom connected. Its interfaces retire after firmware
and driver detection. Reconnecting the sensor restores supported interfaces and
measurements without another acquisition call.

A subscriber can keep a topic name registered after its publisher disappears.
Replace the placeholder with a discovered topic and check publisher count:

```bash
SENSOR_TOPIC='PASTE_DISCOVERED_SENSOR_TOPIC_HERE'
ros2 topic info "$SENSOR_TOPIC" --verbose
```

Disconnecting **the Axiom itself** ends that session. With manual settings, reconnect
the board and request acquisition again:

```bash
ros2 service call /axiom/connect axiom_interfaces/srv/Connect '{device_uri: ""}'
ros2 service call /axiom/publish_data_subscription \
  axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 20.0}'
```

`auto_reconnect: false` leaves unexpected loss recovery manual. An intentional
disconnect disables automatic reconnect. The subscription rate controls delivery,
rather than the sensor's sampling rate.

## Optional aliases

Merge aliases into an existing board entry, keeping its connection settings:

```yaml
    topic_aliases:
      imu/data_raw: {type: LSM6DS, source: imu/data_raw}
      range: {type: VL53L4CD, source: range}
      thermal/image: {type: AMG8833, source: thermal/image}
```

This is a fragment, not a replacement board file. Under board `axiom`, the matching
aliases become `/axiom/imu/data_raw`, `/axiom/range` and `/axiom/thermal/image`.
They preserve identity-based topics and share source timestamps and frame IDs.
An alias binds only when exactly one matching device is online, resolved and fresh.
For ambiguity, add string `bus` and `address` selectors from the inventory, or use
the identity-based topic. Stop acquisition/disconnect, then relaunch the driver
after changing its read-only configuration.

## Descriptor services

Commands appear under `/axiom/bus_BUS/device_ADDRESS/commands/COMMAND`. Discover
the exact path and inspect the descriptor's argument order, units and allowed values:

```bash
ros2 service list -t
ros2 topic echo /axiom/device_metadata --qos-durability transient_local --once
```

For a sensor exposing `set_sample_rate`, replace the service path below and choose
a rate it actually advertises; 52 Hz is an illustrative LSM6DS value:

```bash
RATE_SERVICE='PASTE_DISCOVERED_SAMPLE_RATE_SERVICE_HERE'
ros2 service call "$RATE_SERVICE" \
  axiom_interfaces/srv/DeviceCommand '{values: [52.0]}'
```

Numeric `values` follow descriptor order and units. No-argument commands use
`{values: []}`. Success means firmware acknowledgement, not physical completion of
actuator movement. Unsupported custom value formats are not advertised as callable
services.

## Multiple boards

Use separate namespace keys and endpoints for **different physical Axioms**.
Replace the USB path and illustrative Wi-Fi address below:

```yaml
axioms:
  axiom/front:
    transport: serial
    serial.port: /dev/serial/by-id/REPLACE_WITH_FRONT_AXIOM
    auto_connect: false
    auto_reconnect: false
    autosub: false
  axiom/rear:
    transport: ws
    device_uri: ws://192.0.2.11/ws
    auto_connect: false
    auto_reconnect: false
    autosub: false
```

Save this in the board file selected by `machine.env`, with one `axioms` mapping.
Stop/disconnect any existing single-board driver before starting the multi-board
launch. The [tmux helper](tmux.md) can hold the launch in Terminal 1, service calls
in Terminal 2, and one board's monitor in each of Terminals 3 and 4.

In Terminal 1:

```bash
ros2 launch axiom_driver multi_axiom.launch.py \
  boards_file:="$AXIOM_ROS_BOARDS_FILE"
```

In Terminal 2:

```bash
ros2 service call /axiom/front/connect axiom_interfaces/srv/Connect '{device_uri: ""}'
ros2 service call /axiom/front/publish_data_subscription \
  axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 20.0}'
ros2 service call /axiom/rear/connect axiom_interfaces/srv/Connect '{device_uri: ""}'
ros2 service call /axiom/rear/publish_data_subscription \
  axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 20.0}'
```

Each driver has independent connection, acquisition, metadata, queues, aliases and
frame prefix. Duplicate namespaces, frame prefixes and configured endpoints are
rejected within this launch. The check does not detect drivers in other launches
or identify one physical board reached through different transports.

For unattended startup, opt into `auto_connect: true` and `autosub: true`.
`auto_reconnect: true` separately enables unexpected-loss retries. The manual
example above enables none of these flags.

Stop echoes/viewers, then clean up in Terminal 2 while the launch is still running:

```bash
ros2 service call /axiom/front/publish_data_subscription \
  axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 0.0}'
ros2 service call /axiom/front/disconnect axiom_interfaces/srv/Disconnect '{}'
ros2 service call /axiom/rear/publish_data_subscription \
  axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 0.0}'
ros2 service call /axiom/rear/disconnect axiom_interfaces/srv/Disconnect '{}'
```

Finally stop the launch with Ctrl+C. Other consumers should use ROS subscriptions,
rather than additional firmware acquisition connections to the same board.

Published walkthrough: [Sensors and multiple boards](https://userguides.robotical.io/axiom/ros2/sensors_and_boards).
