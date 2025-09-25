# axiom_driver

This package provides the main ROS 2 driver node for the Axiom device.

## Node: axiom_bridge_node

### Parameters
- `device_uri` (string): WebSocket URI of the device (e.g., `ws://192.168.1.10/devjson`)
- `auto_connect` (bool): Connect automatically on startup
- `frame_id` (string): Frame ID to stamp sensor messages

### Services
- `/connect` (`axiom_interfaces/srv/Connect`): Connect to the device
- `/disconnect` (`axiom_interfaces/srv/Disconnect`): Disconnect from the device
- `/ping` (`axiom_interfaces/srv/Ping`): Measure round-trip time
- `/get_connection_state` (`axiom_interfaces/srv/GetConnectionState`): Query connection status

### Topics (published)
- `imu/data_raw` (`sensor_msgs/msg/Imu`)
- `range/front` (`sensor_msgs/msg/Range`)
- `range/short` (`sensor_msgs/msg/Range`)
- `environment/temperature` (`sensor_msgs/msg/Temperature`)
- `environment/humidity` (`sensor_msgs/msg/RelativeHumidity`)
- (future) `/diagnostics` (`diagnostic_msgs/msg/DiagnosticArray`)

### Launch
- `axiom_minimal.launch.py`: starts `axiom_bridge_node` with parameters.
