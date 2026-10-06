# axiom_driver

The driver separates transport/session code (`core/session.py`, `core/rpc.py`),
metadata and device lifetime (`core/registry.py`), decoding (`core/attributes.py`,
`core/custom.py`, `core/decoding.py`), device clocks (`core/timing.py`), ordered
processing (`core/pipeline.py`) and ROS message contracts (`ros_adapters.py`).
The pure client has no `rclpy` dependency. The node owns a bounded receive queue,
a decode/configuration worker and a four-thread ROS executor. Two RPC service slots
leave room for disconnect/state callbacks while firmware requests wait.

## Configuration

Copy [config/axiom.yaml](config/axiom.yaml) and pass `params_file:=/absolute/path.yaml`.
Explicit launch arguments override the file. Connection, reconnection and acquisition
are manual by default for both launches and direct nodes. Startup parameters are
read-only. Use services for runtime connection, subscription and sample-rate changes.

| Parameter | Default | Meaning |
|---|---|---|
| `transport` | `ws` | `ws` or `serial` |
| `device_uri` | `ws://192.168.1.7/ws` | Framed firmware endpoint |
| `ws_pcol` | `RICSerial` | HDLC-framed RIC; `RICFrame` requires matching firmware endpoint |
| `serial.port`, `serial.baud` | `/dev/ttyUSB0`, `115200` | USB serial connection |
| `serial.mode` | `auto` | `auto`/`overascii` send OverAscii; `ascii` uses console REST |
| `serial.timeout` | `0.02` | Serial read timeout in seconds |
| `auto_connect`, `auto_reconnect` | false, false | Opt into startup connection and unexpected-loss retries |
| `reconnect_interval` | `2.0` | Minimum reconnect delay, seconds |
| `autosub`, `publish_rate_hz` | false, `10.0` | Opt into devjson on connection; delivery rate, not sensor ODR |
| `publish_trigger` | `time` | `time`, `change`, `timeorchange` |
| `rpc_default_timeout` | `3.0` | Response timeout, seconds, maximum 60 |
| `metadata_refresh_s` | `30.0` | Refresh active device metadata; changed profiles retire old interfaces and timing |
| `receive_queue_depth` | `256` | Whole devjson messages; full queue drops incoming messages |
| `stale_after_s` | `5.0` | No-publication diagnostic threshold |
| `sensor_qos.reliability`, `sensor_qos.depth` | `best_effort`, `10` | Default measurement QoS |
| `sensor_qos.overrides` | `'{}'` | JSON mapping relative topic → depth/reliability overrides |
| `topic_aliases` | `'{}'` | JSON mapping relative aliases → type/source and optional bus/address preferences |
| `frame_id` | `axiom` | Frame-name prefix; no global mount frame is implied |
| `sensor_frames` | `'{}'` | JSON mapping `bus:hex-address` → actual sensor frame |
| `range.field_of_view` | `0.0` | Radians; zero means unspecified, configure for your sensor |
| `publish_custom_messages` | true | Publish legacy specialized messages alongside standard types |

For example, inside a parameter file:

```yaml
/**:
  ros__parameters:
    sensor_frames: '{"1:6a":"imu_link","1:29":"front_range_link"}'
    sensor_qos.overrides: '{"bus_1/device_29/range":{"reliability":"reliable","depth":20}}'
```

QoS override keys are exact relative topic names, without the board namespace.
BEST_EFFORT publishers require compatible subscribers. RELIABLE delivery does not
recover samples already lost in firmware or the bridge's bounded queues.

Frame defaults are `axiom_bus_1_device_6a` etc. Provide mounting transforms with your
robot URDF/`robot_state_publisher` or measured static transforms. Sensor axes are
preserved; naming a frame does not rotate data. IMU orientation is unavailable
(`orientation_covariance[0]=-1`); acceleration includes gravity, in m/s², gyro rad/s.
The driver does not invent calibration, covariance, mounting transforms or fusion.

### Optional topic aliases

Identity-based topics are always preserved. The packaged `config/hotplug.yaml`
adds `/axiom/imu/data_raw` for LSM6DS and `/axiom/range` for VL53L4CD. No aliases
are enabled in the normal `axiom.yaml`. For a preferred sensor, use its normalized
bus/address strings from the inventory:

```yaml
/**:
  ros__parameters:
    topic_aliases: '{"front_range":{"type":"VL53L4CD","source":"range","bus":"1","address":"129"}}'
```

Rules bind only when exactly one matching device is online, resolved and fresh.
An ambiguous rule has no publisher; use a bus/address preference or the canonical
topic. Aliases share their source messages, timestamps and frame IDs. They live
beneath the board namespace and follow hot plugging automatically.

### Multiple boards

Copy `config/two_axioms.yaml`, set separate USB paths or WebSocket URIs, then run:

```bash
ros2 launch axiom_driver multi_axiom.launch.py boards_file:=/absolute/path/axioms.yaml
```

Each YAML key is a namespace, e.g. `axiom/front`. Its values are driver parameters;
JSON map parameters can also be YAML mappings here. Each driver has independent
connection, acquisition, metadata, queues and aliases. A frame prefix is derived
from the namespace unless explicitly supplied. The launch rejects duplicate
namespaces, frame prefixes and connections. Default connection and acquisition
remain manual; call each board's services separately.

## Topics

All names are relative to the node namespace. Device identity is bus + normalized
hex address, independent of mutable names/types. Non-alphanumeric identity bytes
are escaped injectively. Group `x` uses the base path; other groups add `group_<id>`.

| Topic | Type / contract |
|---|---|
| `devices` | String JSON inventory; reliable, transient local |
| `device_metadata` | String JSON firmware handshake + resolved per-device metadata + generation; reliable, transient local |
| `raw/devjson` | String JSON `{generation, received_ns, payload}` before decoding |
| `diagnostics` | DiagnosticArray: connection, stale RX, errors, counters, queue loss, timing/ownership policy |
| `serial_console` | Non-JSON console lines |
| `bus_<bus>/device_<addr>/sample` | DeviceSample for every decoded row, including raw/engineering/SI values and validity |
| `…/data` | String JSON convenience view |
| `…/imu/data_raw` | sensor_msgs/Imu when all six axes have known SI units |
| `…/range` | sensor_msgs/Range in metres; invalid range is NaN |
| `…/temperature`, `…/humidity` | Temperature (°C), RelativeHumidity (0..1) |
| `…/thermal/grid` | ThermalGrid preserving the metadata pixel array |
| `…/joint_states` | Observed servo angle in radians; no invented velocity/effort |
| `…/battery` | BatteryState with unavailable quantities NaN |
| `…/imu/axiom`, `…/range/raw`, `…/power/raw` | Optional compatibility messages |

Invalid values are NaN in numeric messages and `null` in JSON; raw values and
validity remain available. Unknown physical units remain engineering values in
DeviceSample, with SI fields unset. Grams of mass are not acceleration.

Offline, removed, stale and replaced devices retire their publishers and descriptor
services. Reconnecting a supported sensor recreates them without restarting the
driver or acquisition. A subscriber can keep a topic name registered after its
publisher disappears; inspect publisher count with `ros2 topic info --verbose`.
Unchanged metadata refreshes preserve publishers and device clock estimates.

## Services

All success responses require a firmware acknowledgement where an RPC is involved.

Live descriptors also create `bus_<bus>/device_<addr>/commands/<command>` services
of type `axiom_interfaces/srv/DeviceCommand`, including output-only devices.
The inventory includes command names, paths and descriptors. Numeric `values`
follow descriptor argument order and units; no-argument commands use `[]`.
Spaces and special characters in names are escaped. `_conf.rate` becomes
`set_sample_rate` and uses the firmware configuration API to keep sampling and
polling settings consistent.

```bash
ros2 service call /axiom/bus_1/device_76a/commands/set_sample_rate axiom_interfaces/srv/DeviceCommand '{values: [52.0]}'
# For a connected LED module, use its discovered bus/address:
ros2 service call /axiom/bus_1/device_23/commands/pixels axiom_interfaces/srv/DeviceCommand '{values: [0.0, 0.0, 16.0, 16.0]}'
ros2 service call /axiom/bus_1/device_23/commands/off axiom_interfaces/srv/DeviceCommand '{values: []}'
```

The encoder supports numeric struct formats, descriptor scaling, pixel indices,
and raw write sequences with bounded pauses. Invalid counts, ranges and encodings
are rejected before transmission. Custom `vt` value formats are not advertised as
callable services. Unsupported descriptors remain available in `device_metadata`.
Success means firmware acknowledgment, not physical completion; these quick
configuration/output operations use services rather than ROS actions.

```bash
ros2 service call /axiom/connect axiom_interfaces/srv/Connect '{device_uri: "ws://192.168.1.7/ws"}'
ros2 service call /axiom/get_connection_state axiom_interfaces/srv/GetConnectionState '{}'
ros2 service call /axiom/publish_data_subscription axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 20.0}'
ros2 service call /axiom/set_sample_rate axiom_interfaces/srv/SetSampleRate '{bus: "1", address: "21", sample_rate_hz: 100.0}'
ros2 service call /axiom/ric_rest_url axiom_interfaces/srv/RicRestUrl '{url_path: "v", timeout: 3.0, ws_pcol: ""}'
ros2 service call /axiom/disconnect axiom_interfaces/srv/Disconnect '{}'
```

Subscription rate zero unsubscribes. `set_sample_rate` only accepts rates advertised
by that device's `_conf.rate` map; firmware configures polling/storage atomically
and returns actual poll interval and retained poll count. Buffered host packets are
dropped/countable across the change so old data is not assigned the new period.
Disconnect cancels pending requests and disables automatic reconnect. Ping measures
an actual version-request round trip; its optional padding is request bytes, not
an echo-throughput guarantee. `ric_rest_url.ws_pcol` may be empty or match the session;
it cannot change framing mid-connection.

Connecting only opens the transport and reads the firmware version. With `autosub=false`,
measurements are forwarded only after a successful `publish_data_subscription` call;
unsolicited packets are ignored. An explicit reconnect needs another acquisition call.
Stopping acquisition leaves the connection open and stops measurement forwarding.
The node still publishes its connection diagnostics and retained inventory; inventory
ages normally while measurements are stopped. Starting `ros2 topic echo` creates a DDS
subscriber; it does not request a firmware stream or change sensor sampling.

For an explicitly unattended launch, set `auto_connect:=true autosub:=true
auto_reconnect:=true`. These flags intentionally combine the manual steps.

## Recording and time

Record `sample` topics for replayable decoded measurements, together with
`device_metadata`, `raw/devjson`, `devices`, `diagnostics`, and your TF topics for
forensic re-decoding. Use rosbag QoS overrides to retain transient-local metadata.
Raw data alone does not contain the decoder profile. Standard messages carry an
estimated acquisition stamp; DeviceSample also stores receipt time, device/poll
time, overflow and `time_quality`. FIFO timestamps are reconstructed using the
advertised/effectively configured sample period. They are not hardware clock sync.

Short counter wraps are unwrapped; long gaps, overlap, detectable resets, overflow
and ROS clock jumps are explicitly flagged. A 16-bit counter cannot distinguish
every reboot from a wrap. Changed metadata and reconnects re-anchor the estimate.
A physical hardware timing/loss benchmark is still required for applications
that depend on acquisition-time accuracy or sustained high-rate delivery.
