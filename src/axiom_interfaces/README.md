# axiom_interfaces

ROS interfaces for the Axiom bridge. See the [driver contracts](../axiom_driver/README.md)
for units, topics, timing and examples. Start with the
[host-driver setup](../../README.md) for installation and manual acquisition.

| Interface | Purpose |
|---|---|
| `DeviceSample` | Header, bus/address/type/group, JSON raw/engineering/SI values + validity, device/poll/receipt times, timing quality and overflow |
| `Imu6`, `VL53L4CDReading`, `AxiomPowerState` | Specialized compatibility views alongside standard sensor_msgs |
| `ThermalGrid` | Width, height and row-major temperature pixels in °C |
| `ShakeEvent` | Triggering IMU header, event number, motion magnitude in m/s² and pulse count; used by the movement lab |
| `Connect` | Device URI → acknowledged readiness |
| `Disconnect` | Cancel pending requests and disable reconnect |
| `GetConnectionState` | Readiness, URI and last error |
| `Ping` | Request padding size → actual RPC round-trip milliseconds |
| `PublishedDataSubscription` | devjson delivery rate (zero unsubscribes); no name field |
| `RicRestUrl` | URL, timeout and optional matching framing → firmware JSON |
| `SetSampleRate` | Bus, hex address and supported sample rate → actual rate, poll interval and retained poll count |
| `DeviceCommand` | Discrete descriptor commands (including enable/configuration): numeric values in descriptor order/units → success, message and firmware response JSON |

Standard IMU, scalar Range and thermal/multizone Image outputs use `sensor_msgs`;
they do not need new custom message definitions. Image values are `32FC1`, in °C
for thermal images or metres for supported multizone range images. See the
[Foxglove walkthrough](../../examples/foxglove/README.md).

Rebuild and source the workspace after interface changes. These interfaces expose
sensor acquisition and configuration; they do not constitute ros2_control actuation.
Servo angles and LED colours use direct subscriptions to standard `Float64`
(radians) and `ColorRGBA` (normalized RGB) messages. They have no `DeviceCommand`
service alternative; see the driver's [command-topic contracts](../axiom_driver/README.md#direct-output-command-topics).
