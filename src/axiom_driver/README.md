# axiom_driver

The driver separates transport/session code (`core/session.py`, `core/rpc.py`),
metadata and device lifetime (`core/registry.py`), decoding (`core/attributes.py`,
`core/custom.py`, `core/decoding.py`), device clocks (`core/timing.py`), ordered
processing (`core/pipeline.py`) and ROS message contracts (`ros_adapters.py`).
The pure client has no `rclpy` dependency. The node owns a bounded receive queue,
a decode/configuration worker. Direct bridge execution uses a four-thread ROS
executor; discovery manages its bridges with one ROS callback thread. Two RPC service slots
leave room for disconnect/state callbacks while firmware requests wait.

## Automatic discovery

The normal entry point is `ros2 launch axiom_driver axiom.launch.py`. It discovers
USB and mDNS-advertised Wi-Fi endpoints, verifies the firmware MAC, and runs one
bridge per physical board. Names and frame prefixes are stable across replug and
transport changes. USB is preferred. The retained `/axiom_discovery/boards`
inventory reports board IDs and assigned namespaces. See
[automatic startup](../../docs/automatic-startup.md) for optional identity rules,
robot membership, endpoint fallbacks, manual control and ownership limits.

## Configuration

For host firmware selection, ROS installation and the shared local files, start
with the [repository README](../../README.md). These contracts describe the host
driver; native ROS/Zenoh firmware is a separate workflow. The examples use
user-chosen namespaces and illustrative sensor identities. Inspect the actual
inventory before selecting a topic, frame, device address or command.

`scripts/setup_env.sh` loads `config/machine.env` and the built workspace.
`config/boards.yaml` supplies one endpoint per namespace to both driver launches.
The single-board launch reads its parameter file, then board settings, then
explicit launch overrides. The multi-board launch merges driver defaults with
each board entry. See [sensor/board configuration](../../docs/sensors-and-boards.md).


Copy [config/axiom.yaml](config/axiom.yaml) and pass `params_file:=/absolute/path.yaml`.
Explicit launch arguments override the file. Connection, reconnection and acquisition
are enabled by default. Set `auto_connect`, `auto_reconnect` and `autosub` to false
for explicit manual operation. Startup parameters are
read-only. Use services for runtime connection, subscription and sample-rate changes.

| Parameter | Default | Meaning |
|---|---|---|
| `transport` | `ws` | `ws` or `serial` |
| `device_uri` | empty | Configure an explicit framed `/ws` endpoint, or use discovery |
| `ws_pcol` | `RICSerial` | HDLC-framed RIC; `RICFrame` requires matching firmware endpoint |
| `serial.port`, `serial.baud` | empty, `115200` | Explicit USB serial connection |
| `serial.mode` | `auto` | `auto`/`overascii` send OverAscii; `ascii` uses console REST |
| `serial.timeout` | `0.02` | Serial read timeout in seconds |
| `auto_connect`, `auto_reconnect` | true, true | Startup connection and unexpected-loss retries |
| `reconnect_interval` | `2.0` | Minimum reconnect delay, seconds |
| `autosub`, `publish_rate_hz` | true, `10.0` | Acquire devjson on connection; delivery rate, not sensor ODR |
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
    sensor_qos.overrides: '{"vl53l4cd_b1_29/range":{"reliability":"reliable","depth":20}}'
```

QoS override keys are exact relative topic names, without the board namespace.
Overrides match exact current topic paths only; no old-name fallback is applied.
Configured aliases use their own override or the default sensor QoS.
BEST_EFFORT publishers require compatible subscribers. RELIABLE delivery does not
recover samples already lost in firmware or the bridge's bounded queues.

Frame defaults are `axiom_bus_1_device_6a` etc. Provide mounting transforms with your
robot URDF/`robot_state_publisher` or measured static transforms. Sensor axes are
preserved; naming a frame does not rotate data. IMU orientation is unavailable
(`orientation_covariance[0]=-1`); acceleration includes gravity, in m/s², gyro rad/s.
The driver does not invent calibration, covariance, mounting transforms or fusion.

### Optional topic aliases

Each sensor has model/location topics. The packaged `config/hotplug.yaml`
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
namespaces, frame prefixes and connections. Default connection, recovery and acquisition
are automatic. Set the three startup flags to false for manual service control.

## Topics

All names are relative to the node namespace. Device identity is bus + normalized
hex address, independent of mutable names/types. Non-alphanumeric identity bytes
are escaped injectively. Group `x` uses the base path; other groups add `group_<id>`.

### Readable sensor names

Every measurement uses `<model>_b<bus>_<hex-address>/<output>`. The descriptor
model is lowercased; non-alphanumeric UTF-8 bytes (including literal underscores)
are escaped as `_<hex-byte>`. A leading-digit or escaped model gets the prefix
`sensor_`, keeping topics visible in normal ROS listings. Bus values use the same
escaping. With the illustrative board namespace `/axiom`:

| Measurement | Topic example |
|---|---|
| Scalar distance | `/axiom/vl53l4cd_b1_129/range` |
| Six-axis IMU | `/axiom/lsm6ds_b1_76a/data_raw` |
| Thermal image | `/axiom/amg8833_b1_169/image` |
| Multizone distance image | `/axiom/vl53l5cx_b1_129/image` |

The location identifier is always present. Adding a second sensor does not rename
the first: two distance sensors might use `vl53l4cd_b1_29` and
`vl53l4cd_b1_129`; the same address on another bus uses `vl53l4cd_b2_29`.
Reconnecting at the same location preserves its name; moving it to a different
firmware bus/address can change it. A replacement model changes the public root.
Non-`x` payload groups use `<sensor-instance>/group_<escaped-id>/<output>`.

The `devices` inventory's `topic` is the relative sensor root, or `null` while
metadata is unresolved. Raw `bus` and `address` fields remain available for
firmware operations. `public_topics` maps payload group, then canonical output
suffix, to an actually published relative topic:

```json
{"topic":"lsm6ds_b1_76a","public_topics":{"x":{"sample":"lsm6ds_b1_76a/sample","data":"lsm6ds_b1_76a/data","data_raw":"lsm6ds_b1_76a/data_raw"}}}
```

Consumers should skip unresolved rows and refresh their subscriptions when
`public_topics` changes: metadata may resolve before the first measurement.
The parallel `output_info[group][suffix]` map describes each published canonical
output with `message_type` (for example `sensor_msgs/msg/Illuminance`) and `unit`.
The unit is `null` for unitless/unspecified values and messages without a single
measurement unit, such as IMU, generic JSON, booleans and text. Both maps become
empty when the device's publishers retire.
Output-only devices have a readable root, command inputs and services, with
an empty output map. A configured alias reserves its exact path even while
unbound. The canonical output at that path is suppressed and omitted from
`public_topics`, so two sources cannot be mixed into that publisher. Offline,
stale, removed or replaced devices and ended sessions retire their publishers.

### Topic contracts

All `…` paths below are beneath the discovered sensor root (and optional group).

| Topic | Type / contract |
|---|---|
| `devices` | String JSON inventory; reliable, transient local |
| `device_metadata` | String JSON firmware handshake + resolved per-device metadata + generation; reliable, transient local |
| `raw/devjson` | String JSON `{generation, received_ns, payload}` before decoding |
| `diagnostics` | DiagnosticArray: connection, stale RX, errors, counters, queue loss, timing/ownership policy |
| `serial_console` | Non-JSON console lines |
| `…/sample` | DeviceSample for every decoded row, including raw/engineering/SI values and validity |
| `…/data` | String JSON convenience view |
| `…/data_raw` | sensor_msgs/Imu when all six axes have known SI units |
| `…/range` | sensor_msgs/Range for scalar distances in metres; invalid range is NaN |
| `…/image` | sensor_msgs/Image, `32FC1`; temperatures in °C or multizone distances in metres; invalid zones are NaN |
| `…/temperature`, `…/humidity` | Temperature (°C), RelativeHumidity (0..1) |
| `…/<light-attribute>` | sensor_msgs/Illuminance for recognised light quantities in lux; variance 0 means unknown |
| `…/<attribute>` | std_msgs/Float64, Bool or String for remaining supported scalar attributes |
| `…/grid` | ThermalGrid preserving the metadata pixel array |
| `…/joint_states` | Observed servo angle in radians; no invented velocity/effort |
| `…/battery` | BatteryState with unavailable quantities NaN |
| `…/imu/axiom`, `…/range/raw`, `…/power/raw` | Optional specialized messages |

A descriptor declaring both thermal and distance grids uses `thermal/image` and
`range/image` instead of `image` to keep meanings separate. The decision follows
descriptor capabilities independently of sample arrival order; only those dual
profiles use these two output suffixes.

### Descriptor-driven light and scalar outputs

Existing descriptors supply these outputs without ROS-specific metadata or a
firmware update. For example, an LTR-390 publishes `ambient` as
`sensor_msgs/msg/Illuminance` in lux and `UVI` as `std_msgs/msg/Float64` in the
descriptor's `index` unit. Attribute case is preserved. Recognised light names
are `ambient`, `als`, `white`, `visible`, `illuminance` and `light` (case
insensitive), with a known lux conversion. Ambiguous channels such as `ir` use
the numeric fallback even if their descriptor labels them lux.

Remaining numeric scalars publish their decoded SI value when available,
otherwise the decoded engineering value and original unit. Divisors, offsets
and other descriptor transforms are applied once by the decoder. Unknown units
remain unknown; raw counters are never substituted for missing readings.
Numeric values use Float64, including fractional engineering values from integer
wire fields. Integer values above 2^53 may lose precision; the generic `sample`
retains raw values. Descriptor booleans use Bool and decoded text uses String.
Invalid/nonfinite numeric readings publish NaN; invalid boolean/text readings
are omitted. Negative illuminance also publishes NaN.

By default, existing semantic adapters take priority: IMU axes, range values and their
validity flag, temperature/humidity, servo position, battery voltage and image
pixels/dimensions are not duplicated as scalar outputs. Other attributes such
as sensor status or auxiliary readings can still publish scalars. Arrays and
structured values have no generic scalar output; use a supported image adapter
or the unchanged `sample`/`data` JSON outputs.

Float64, Bool and String carry only `data`, without a header or unit field. Use
`output_info` for units and `sample` for timestamps, validity and complete data.
These are practical fallbacks; an appropriate semantic sensor message takes
precedence when a supported mapping is available.

Unsafe attribute characters are escaped using the same byte encoding as sensor
names. Names that would be hidden, start with a digit or collide with reserved
adapter outputs gain an `attribute_` prefix (for example a numeric attribute
named `data` uses `attribute_data`). Copy the actual suffix from `public_topics`
for alias `source` and QoS settings. Scalar alias sources are single suffix
tokens, for example:

```yaml
topic_aliases:
  light: {type: LTR-390, source: ambient}
  uv: {type: LTR-390, source: UVI}
```

### Optional ROS mappings in descriptors

A descriptor can explicitly select a supported scalar message type with an
optional `ros` block inside `devInfoJson`. The host receives this as `devinfo.ros`
through the existing metadata endpoint. For example, add this fragment alongside
`type`, `resp` and `actions` in a Device Library descriptor's `devInfoJson`:

```json
"ros": {
  "version": 1,
  "attributes": {
    "photodiode": {"message_type": "sensor_msgs/msg/Illuminance"},
    "tempC": {"message_type": "sensor_msgs/msg/Temperature"},
    "UVI": {"message_type": "std_msgs/msg/Float64"}
  }
}
```

Each key is an exact, case-sensitive attribute name declared in `resp.a`.
`photodiode`, for example, must have a scalar numeric layout and a known lux
unit; declaring Illuminance does not convert a raw count into lux. A valid
declaration removes the need for the automatic light-name rule. Output suffixes
still follow the attribute's name and the escaping/reservation rules above.

| `message_type` | Required decoded input |
|---|---|
| `sensor_msgs/msg/Illuminance` | Numeric scalar with normalised unit `lux` |
| `sensor_msgs/msg/Temperature` | Numeric scalar with normalised unit `degC` |
| `sensor_msgs/msg/RelativeHumidity` | Numeric scalar with normalised unit `fraction`, e.g. converted from `%RH` |
| `std_msgs/msg/Float64` | Numeric scalar; decoded SI value when available, otherwise engineering value |
| `std_msgs/msg/Bool` | Descriptor boolean (`o: bool` or a `?` wire field) |
| `std_msgs/msg/String` | Decoded scalar text |

Mapped sensor messages use the sample timestamp, configured sensor frame and
unknown variance (`0`). The same invalid-reading rules apply as for automatic
scalar outputs. Existing descriptor scaling is applied once; mappings have no
extra scaling, unit override, topic rename or arbitrary field-assignment options.

A valid mapping selects that attribute's output type. For example, mapping
`temperature` to Float64 replaces its automatic Temperature publisher at the
same suffix. Compound IMU, range, image, joint and battery outputs continue to
work; an explicitly mapped component such as `gx` additionally gets its own
scalar topic. Unmapped component attributes remain consumed by those adapters.
Arrays are unsupported in this scalar schema and retain their existing image
or generic output handling.

Absent mappings leave the existing behavior unchanged. An unsupported version or
malformed block is ignored with a warning. Unknown attributes, unsupported types,
extra declaration fields and incompatible units/shapes warn and retain that
attribute's automatic mapping/fallback; valid peer declarations still apply.
Warnings appear once per issue per device revision. An attribute absent from one
payload group is simply skipped there. Metadata refresh/replacement retires the
old publishers before the new types appear, including configured aliases.

Aliases and exact QoS overrides work through the same output suffixes, and
`output_info` describes the actual resulting message types and units. Profiles
without this block continue working. The feature is implemented in the host
driver; it adds no native firmware ROS mapping behavior. Firmware/Raft sources
and catalogue profiles are unchanged. Physical Device Library upload, restart
and metadata readback acceptance for this block remains pending.

### Migrating topic configuration

This is a breaking naming change. Old bus/device topic and command-service paths
are removed, with no compatibility option. Select current paths from inventory
and update subscriber topics, bag-recording lists, QoS override keys and sensor
preferences. Alias **paths** remain user chosen, but their `source` selectors now
use `data_raw`, `grid` and `image` rather than the previous `imu/data_raw`,
`thermal/grid` and ordinary `thermal/image`/`range/image` selectors. For example:

```yaml
topic_aliases:
  imu/data_raw: {type: LSM6DS, source: data_raw}
  thermal/image: {type: AMG8833, source: image}
```

The dual-image descriptor exception uses its actual `thermal/image` or
`range/image` source. Other source selectors such as `range`, `sample` and `data`
stay the same. Frame IDs and mounting/TF contracts, raw bus/address fields and
firmware requests are unchanged; topic names and command paths are public ROS
interfaces, not coordinate frames.

Invalid values are NaN in numeric messages and `null` in JSON; raw values and
validity remain available. Unknown physical units remain engineering values in
DeviceSample, with SI fields unset. Grams of mass are not acceleration.

### Grid images and Foxglove

Thermal grids with a `widthxheight` resolution and known Celsius units also emit
`image` alongside `grid` for the marker visualizer. Range arrays advertised as
`vt: "zonegrid"` emit `image`
instead of a scalar `Range`. Other distance arrays remain available in `sample`
and `data` without being collapsed into one distance.

Both images contain row-major, little-endian float32 values, with `step = width * 4`.
They retain the sample's timestamp, frame ID and original zone order, with no
rotation, interpolation or automatic mirroring. The frame remains the configured
sensor frame; no camera calibration or optical-frame transform is fabricated.
Use these as 2D measurement heatmaps. An accurate 3D projection needs a separate
calibration and coordinate-frame contract.

For the VL53L5CX, the descriptor's `gridAttr`, `statusAttr` and `validStatus` select
the dimensions and usable zones (currently statuses 5, 6 and 9). A 4×4 image uses
the first 16 entries of the firmware's fixed 64-entry arrays; an 8×8 image uses all
64. Invalid statuses, invalid decoded values and nonpositive/nonfinite distances
become NaN. Missing or inconsistent dimensions/status arrays are reported through
the existing decode-error diagnostics. Generic messages keep the original
distances and status codes. Display preferences in `vo` do not change the
image's pixel order.

Add an `image` alias source for the selected board to use the
[single-camera Foxglove thermal layout](../../examples/foxglove/README.md#thermal-camera-on-one-axiom).
An `image` alias selected by type `VL53L5CX` provides a separate multizone display.
Image topics use the usual sensor QoS, per-topic overrides and publisher lifecycle.
They are also published when `publish_custom_messages` is false. No additional
Python imaging dependency or visualization node is needed for the Image panels.

Offline, removed, stale and replaced devices retire their publishers and descriptor
services. Reconnecting a supported sensor recreates them without restarting the
driver or acquisition. A subscriber can keep a topic name registered after its
publisher disappears; inspect publisher count with `ros2 topic info --verbose`.
Unchanged metadata refreshes preserve publishers and device clock estimates.

## Direct output command topics

The driver subscribes directly to supported output targets advertised by live
descriptors. The `devices` inventory's `command_topics` array provides each exact
relative `topic`, `message_type`, `unit`, original command `name` and `descriptor`.
Indexed LED inputs also include `pixel`. Prefix the relative path with the board's
namespace. These inputs are separate from the measurement `public_topics` map.

| Descriptor command | Topic example beneath a device root | ROS input |
|---|---|---|
| Servo `angle` or `set angle` | `commands/angle` (or the escaped action name) | `std_msgs/msg/Float64`, radians |
| Indexed RGB `LEDPIX` | `commands/pixels/pixel_0`, `pixel_1`, … | `std_msgs/msg/ColorRGBA`, RGB channels in 0..1 |
| Whole-light `color`, `colour` or `rgb` (three-byte or packed `>I`/`06x`) | `commands/colour` (exact action name) | `std_msgs/msg/ColorRGBA`, RGB channels in 0..1 |

RGB alpha is ignored because the supported devices have no transparency channel.
Pixel indexes are zero-based and use the descriptor's index order. The driver
converts RGB channels to bytes and converts servo radians to descriptor units,
including integer wire resolution and range checks. Servo units come from the
action's `u`, then the reported `angle` attribute's `u`; the legacy default is
degrees. Supported units are `degrees`/`deg` and `radians`/`rad`.

```bash
# Copy the actual full angle topic from the board's command_topics inventory.
ANGLE_TOPIC='PASTE_DISCOVERED_ANGLE_TOPIC_HERE'
# Request approximately five degrees using ROS radians.
ros2 topic pub --once "$ANGLE_TOPIC" std_msgs/msg/Float64 '{data: 0.0872664626}'
# Copy the actual full topic for the desired LED pixel.
COLOUR_TOPIC='PASTE_DISCOVERED_PIXEL_TOPIC_HERE'
# Set that pixel to red using normalized RGB values.
ros2 topic pub --once "$COLOUR_TOPIC" std_msgs/msg/ColorRGBA '{r: 1.0, g: 0.0, b: 0.0, a: 1.0}'
```

Command subscriptions use reliable, volatile QoS with depth one. Targets are
validated without blocking the ROS executor; the existing pipeline worker sends
them through the existing firmware protocol, allowing acquisition between writes.
Only the latest pending target per topic is kept. Different pixels retain separate
targets. Identical acknowledged values are deduplicated. Removed, stale or replaced
devices and ended sessions discard pending targets and retire subscriptions.
Queued targets older than `rpc_default_timeout` are discarded. Firmware failures
are reported through driver logs/diagnostics; topic publication is not a physical
completion acknowledgement. Failed targets are not retried without fresh input.

The former angle and LED-colour services are removed, with no compatibility mode.
The remaining `commands` inventory array lists acknowledged services such as
enable/disable, LED brightness/off, sample-rate and other configuration operations.
Direct angle publication does not automatically enable a servo. Use its advertised
enable service first, or use the [slider demo](../../docs/servo-slider.md), which
enables once on startup by default. Acknowledged enable/off operations discard
earlier pending targets for that device and invalidate the deduplication cache.
StackLight services do the same. A whole-light colour invalidates pixel target
caches; a pixel change invalidates the whole-light cache without affecting other
pixels. This permits returning to the same colour after another control changes it.

The optional [RViz lighting panel](../../docs/lighting.md) discovers these interfaces
and offers whole colour, brightness, Off and supported four-tier stack patterns.

## Services

All success responses require a firmware acknowledgement where an RPC is involved.

Other supported descriptor commands create `<sensor-instance>/commands/<command>` services
of type `axiom_interfaces/srv/DeviceCommand`, including output-only devices.
The inventory includes command names, paths and descriptors. Numeric `values`
follow descriptor argument order and units; no-argument commands use `[]`.
Spaces and special characters in names are escaped. `_conf.rate` becomes
`set_sample_rate` and uses the firmware configuration API to keep sampling and
polling settings consistent.

Copy each exact service path from discovery into these placeholders. The values
below are examples; use only values and commands advertised by the device's live
descriptor (52 Hz is an illustrative LSM6DS rate):

```bash
RATE_SERVICE='PASTE_DISCOVERED_SAMPLE_RATE_SERVICE_HERE'
ros2 service call "$RATE_SERVICE" axiom_interfaces/srv/DeviceCommand '{values: [52.0]}'
LED_OFF_SERVICE='PASTE_DISCOVERED_LED_OFF_SERVICE_HERE'
ros2 service call "$LED_OFF_SERVICE" axiom_interfaces/srv/DeviceCommand '{values: []}'
```

The encoder supports numeric struct formats, descriptor scaling, pixel indices,
and raw write sequences with bounded pauses. Invalid counts, ranges and encodings
are rejected before transmission. Four-tier `vt: stacklight` commands are supported
when `f: STACKLIGHT`, `t: '>HBBBB'` and `NY: 4`; see the
[lighting guide](../../docs/lighting.md) for argument order and limits.
Other custom formats are not callable. Unsupported descriptors remain in `device_metadata`.
Success means firmware acknowledgment, not physical completion; these quick
configuration/output operations use services rather than ROS actions.

```bash
ros2 service call /axiom/connect axiom_interfaces/srv/Connect '{device_uri: ""}'
ros2 service call /axiom/get_connection_state axiom_interfaces/srv/GetConnectionState '{}'
ros2 service call /axiom/publish_data_subscription axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 20.0}'
ros2 service call /axiom/ric_rest_url axiom_interfaces/srv/RicRestUrl '{url_path: "v", timeout: 3.0, ws_pcol: ""}'
ros2 service call /axiom/disconnect axiom_interfaces/srv/Disconnect '{}'
```

The empty connect URI uses the configured connection. Replace `/axiom` with
your board namespace. For `SetSampleRate`, supply the actual inventory `bus`,
hexadecimal `address` and a rate listed in that device's configuration map; see
the [interface definition](../axiom_interfaces/srv/SetSampleRate.srv).

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
unsolicited packets are ignored. An explicit board reconnect needs another acquisition call. Sensor hot swapping
while its board stays connected does not need that call.
Stopping acquisition leaves the connection open and stops measurement forwarding.
The node still publishes its connection diagnostics and retained inventory; inventory
ages normally while measurements are stopped. Starting `ros2 topic echo` creates a DDS
subscriber; it does not request a firmware stream or change sensor sampling.

Automatic startup is the default. For an explicitly manual launch, set
`auto_connect:=false autosub:=false auto_reconnect:=false`. With `autosub=true`,
explicit connection requests acquisition too; use `autosub=false` to keep these
steps separate.

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
