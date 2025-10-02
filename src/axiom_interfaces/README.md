# axiom_interfaces

This package defines the custom ROS 2 service interfaces used by the Axiom driver.

## Services

- **Connect.srv**
  - Request: `string device_uri`
  - Response: `bool success`, `string message`

- **Disconnect.srv**
  - Request: (empty)
  - Response: `bool success`, `string message`

- **Ping.srv**
  - Request: `uint32 payload_size`
  - Response: `bool success`, `float32 rtt_ms`, `string message`

- **PublishedDataSubscription.srv**
  - Request: `string name`, `float32 rate_hz`
  - Response: `bool success`, `string message`

- **GetConnectionState.srv**
  - Request: (empty)
  - Response: `bool connected`, `string device_uri`, `string last_error`
