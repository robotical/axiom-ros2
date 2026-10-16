# Sensors and multiple Axioms

Complete the [host-driver setup](../README.md) and leave discovery running.
Automatic startup, stable board names and optional identity rules are described
in [automatic startup](automatic-startup.md).
The examples use the namespace `/axiom`. Substitute your configured namespace
and the actual discovered sensor identities. `boards.yaml` describes board
connections and optional aliases; sensors do not need to be listed individually.

## Discover topics and commands

In a prepared ROS terminal:

```bash
ros2 topic list -t --no-daemon
ros2 service list -t
ros2 topic echo /axiom/devices --qos-reliability reliable --qos-durability transient_local --once
```

Measurements use names such as `/axiom/lsm6ds_b1_76a/data_raw`,
`/axiom/vl53l4cd_b1_129/range` and `/axiom/amg8833_b1_169/image`. The pattern is
`/<board>/<lowercase-model>_b<bus>_<hex-address>/<output>`. Bus and address always
distinguish sensor instances, so another sensor of the same model does not rename
an existing one. Unusual model/bus characters are escaped. Copy exact paths from
the topic list or `public_topics` in the device inventory.

Inventory `topic` is the relative sensor root; unresolved metadata rows have
`topic: null` and should be skipped. `public_topics.x.data_raw` identifies a
published IMU topic. Other payload groups have separate `group_<id>` paths.
The map gains outputs after their first sample and becomes empty when publishers
retire. Output-only devices can expose commands without measurement topics.
The matching `output_info[group][suffix]` map lists each canonical output's
`message_type` and `unit`; a `null` unit means unspecified/unitless or no single
unit for the message.

| Output suffix | Type and units |
|---|---|
| `data_raw` | `sensor_msgs/msg/Imu`; acceleration m/s² including gravity, angular velocity rad/s; no fused orientation |
| `range` | `sensor_msgs/msg/Range`; scalar distance in metres; invalid readings are NaN |
| `image` | `sensor_msgs/msg/Image`; thermal °C or supported multizone distances in metres, `32FC1`; invalid pixels are NaN |
| `temperature` | `sensor_msgs/msg/Temperature`; °C |
| `humidity` | `sensor_msgs/msg/RelativeHumidity`; fraction from 0 to 1 |
| Light attribute, e.g. `ambient` | `sensor_msgs/msg/Illuminance`; recognised light quantities in lux |
| Other scalar attribute, e.g. `UVI` | `std_msgs/msg/Float64`, `Bool` or `String`; unit recorded in `output_info` |
| `grid` | `axiom_interfaces/msg/ThermalGrid`; dimensions and pixel temperatures |
| `sample` | `axiom_interfaces/msg/DeviceSample`; decoded values, validity and timing |
| `data` | `std_msgs/msg/String`; JSON decoded measurement view |

A descriptor with both thermal and distance grids uses `thermal/image` and
`range/image` to distinguish them. Supported profiles supply generic `sample` and
`data`; standard typed outputs additionally need a supported mapping and known
units. A Device Library profile does not automatically add a custom binary decoder.

LTR-390, for example, publishes `ambient` in lux as Illuminance and `UVI` in the
descriptor's `index` unit as Float64. These outputs use the existing descriptor;
no firmware update or sensor-specific ROS configuration is required. Numeric
fallbacks use decoded SI values when known, otherwise decoded engineering values.
An unknown unit is not guessed. Existing semantic adapters consume their fields
so IMU axes, range values and grid pixels are not duplicated as scalar topics.
Arrays remain in the generic outputs unless a dedicated adapter handles them.

Invalid numeric readings publish NaN; invalid bool/text readings are omitted.
Scalar messages contain only `data`, without timestamps or units: read inventory
for units or `sample` for timing and validity. Attribute names retain their case;
unsafe names are escaped and collisions such as a numeric `data` attribute use
`attribute_data`. Copy actual paths from inventory. See the
[scalar contracts](../src/axiom_driver/README.md#descriptor-driven-light-and-scalar-outputs)
for the light mapping rules and fallback limits.

Old bus/device topic and command paths are removed. Update topic selections,
recording lists, exact QoS override keys and alias `source` selectors when pulling
this version. Frame IDs and firmware bus/address fields remain unchanged. See the
[full contracts and migration keys](../src/axiom_driver/README.md#migrating-topic-configuration).

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
      imu/data_raw: {type: LSM6DS, source: data_raw}
      range: {type: VL53L4CD, source: range}
      thermal/image: {type: AMG8833, source: image}
      light: {type: LTR-390, source: ambient}
      uv: {type: LTR-390, source: UVI}
```

This is a fragment, not a replacement board file. Under board `axiom`, the matching
aliases include `/axiom/imu/data_raw`, `/axiom/range`, `/axiom/thermal/image`,
`/axiom/light` and `/axiom/uv`.
They add convenience paths to the sensor topics and share source timestamps and frame IDs.
Alias `source` values use the canonical output suffixes in the table above.
If an alias uses a generated readable path, the alias takes precedence: the
automatic output at that exact path is suppressed, even while the alias is
unbound, and is not listed in `public_topics`.
An alias binds only when exactly one matching device is online, resolved and fresh.
For ambiguity, add string `bus` and `address` selectors from the inventory, or use
the canonical sensor topic. Stop acquisition/disconnect, then relaunch the driver
after changing its read-only configuration.

## Descriptor services

Commands appear under `/axiom/MODEL_bBUS_ADDRESS/commands/COMMAND`. Discover
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
rejected within this launch. Current host-driver sessions also take per-user endpoint and firmware-MAC locks
on the same computer. Discovery deduplicates USB and Wi-Fi endpoints by firmware
MAC; advisory locks do not coordinate other computers or unrelated applications.

Automatic connection, recovery and acquisition are the defaults. The explicit
manual example above disables all three flags. For automatic multi-board startup
without endpoint configuration, use `axiom.launch.py` with optional identity rules
as described in [automatic startup](automatic-startup.md).

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
