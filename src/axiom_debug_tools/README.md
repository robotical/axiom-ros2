# axiom_debug_tools

This package provides small debugging nodes that subscribe to topics published by the Axiom driver.

## Nodes

### `axiom_topic_sniff`
Generic topic sniffer.
- **Parameters**:
  - `topic` (string): topic to subscribe to
  - `type` (string): message type (e.g., `sensor_msgs/msg/Imu`)
- **Output**: Logs JSON-formatted messages and message rate.

### `axiom_imu_monitor`
IMU monitor and sanity checker.
- **Parameters**:
  - `topic` (string, default `bus_1/device_6a/imu/data_raw`)
- **Subscribed topics**:
  - `sensor_msgs/msg/Imu`
- **Output**: Logs acceleration, gyro, estimated bias, frequency, warns if out of range.

### `axiom_range_monitor`
Range monitor for VL53/VL6180.
- **Parameters**:
  - `topic` (string, default `bus_1/device_29/range`)
- **Subscribed topics**:
  - `sensor_msgs/msg/Range`
- **Output**: Logs range in meters, frequency, flags out-of-range.

### `axiom_env_monitor`
Environment monitor for temperature and humidity.
- **Parameters**:
  - `temp_topic` (string, default `bus_1/device_38/temperature`)
  - `hum_topic` (string, default `bus_1/device_38/humidity`)
- **Subscribed topics**:
  - `sensor_msgs/msg/Temperature`
  - `sensor_msgs/msg/RelativeHumidity`
- **Output**: Logs temperature (°C), humidity (%RH), frequency.

Run with `--ros-args -r __ns:=/axiom` to use the default bringup namespace.
Monitor topics use BEST_EFFORT QoS. Use the device inventory for actual addresses.
