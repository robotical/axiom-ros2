# axiom_interfaces

ROS interfaces for the Axiom bridge. See the [driver contracts](../axiom_driver/README.md)
for units, topics, timing and examples.

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
| `DeviceCommand` | Numeric values in live descriptor order/units → success, message and firmware response JSON; endpoint follows device lifetime |

Rebuild and source the workspace after interface changes. These interfaces expose
sensor acquisition and configuration; they do not constitute ros2_control actuation.
