/* Local teaching notes plus the current discovery snapshot; never calls ROS. */
(function (root) {
  'use strict';
  const quote = value => "'" + value.replaceAll("'", "'\\''") + "'";
  const topicNotes = {
    '/axiom/devices': 'JSON inventory of Axiom devices: bus/address identity, device type, online state and metadata readiness. Use it to choose the actual sensor topic prefix; detection alone does not establish a valid reading.',
    '/axiom/device_metadata': 'JSON device schemas fetched from Axiom firmware, including type references and revisions. The driver uses these schemas to decode sensor packets.',
    '/axiom/raw/devjson': 'Raw firmware sensor JSON wrapped with the connection generation and host receipt time. Useful for checking the packet before decoding or conversion to ROS messages.',
    '/axiom/serial_console': 'Text lines from the Axiom serial console, useful for firmware logs and connection troubleshooting.',
    '/marty/status': 'Marty connection and telemetry freshness, motion status, queue length and the last driver error. A running node can publish status while the robot is disconnected.',
    '/marty/telemetry': 'Decoded MartyPy telemetry with its firmware topic identifier, connection generation and JSON values. The timestamp is host receipt time.',
    '/marty/servo_states': 'Marty servo positions, electrical current, flags and communication status. Use joint_states for standard joint position visualization.',
    '/marty/imu/data_raw': 'Marty accelerometer readings in m/s², including gravity. This driver has no orientation or angular velocity measurement for this topic.',
    '/rosout': 'ROS node log messages, including severity, timestamp, logger name and source location.',
    '/parameter_events': 'Notifications when ROS node parameters are created, changed or deleted. Receiving an event does not change any parameters.',
    '/tf': 'Time-varying transforms between coordinate frames, used by RViz and other spatial consumers.',
    '/tf_static': 'Static transforms between coordinate frames. A transient-local publisher retains transforms for compatible late subscribers.',
  };
  const fields = {
    'std_msgs/msg/String': 'data: text. Project inventory, metadata and state topics encode JSON inside this string.',
    'sensor_msgs/msg/Imu': 'header: timestamp and frame; linear_acceleration: x/y/z in m/s²; angular_velocity: rad/s; orientation: quaternion. A covariance starting with −1 marks an unavailable estimate.',
    'sensor_msgs/msg/Range': 'range, min_range and max_range: metres; field_of_view: radians; radiation_type: sensor technology; header: timestamp and frame. This Axiom adapter uses NaN for invalid distances.',
    'sensor_msgs/msg/Temperature': 'temperature: °C; variance: measurement variance; header: timestamp and frame.',
    'sensor_msgs/msg/RelativeHumidity': 'relative_humidity: fraction from 0 to 1; variance: measurement variance; header: timestamp and frame.',
    'sensor_msgs/msg/BatteryState': 'voltage: V; current: A; percentage: fraction from 0 to 1; additional fields describe charge and battery status. Unavailable measurements may be NaN.',
    'sensor_msgs/msg/JointState': 'name identifies each joint; matching arrays hold position in radians or metres, velocity and effort. Unsupported arrays can be empty.',
    'diagnostic_msgs/msg/DiagnosticArray': 'status: diagnostic entries with level, name, message, hardware identifier and key/value details; header: timestamp.',
    'axiom_interfaces/msg/DeviceSample': 'bus/address and device_type identify the sensor. values_json contains decoded values, units and validity. device_time_us, poll_time_us, received_at and time_quality describe measurement timing; invalid JSON values are null.',
    'axiom_interfaces/msg/ThermalGrid': 'width and height: grid dimensions; temperature_c: row-major pixel temperatures in °C; header: timestamp and frame.',
    'marty_interfaces/msg/DriverStatus': 'connected and connection_state: link state; telemetry_fresh and motion_status_valid: validity; moving, paused and queued_movements: motion state; age fields: seconds; last_error: driver error.',
    'marty_interfaces/msg/Telemetry': 'topic_id: firmware telemetry channel; generation: connection session; values_json: SDK values, units and validity; header: host receipt timestamp.',
    'marty_interfaces/msg/ServoStates': 'servos: servo id/name, position_radians, current_amperes, flags, enabled and comms_ok; header: timestamp.',
    'visualization_msgs/msg/MarkerArray': 'markers: shapes, poses, labels, colours and lifetimes for RViz. These are display objects derived from readings.',
    'tf2_msgs/msg/TFMessage': 'transforms: parent/child frame names, translation, rotation and timestamp.',
    'rcl_interfaces/msg/Log': 'level, name and msg describe the log entry; stamp, file, function and line locate it.',
    'rcl_interfaces/msg/ParameterEvent': 'node and stamp identify the change; new_parameters, changed_parameters and deleted_parameters list affected parameters.',
  };
  // Request/response notes match the project's .srv definitions.
  const serviceNotes = {
    'axiom_interfaces/srv/DeviceCommand': ['Runs a command advertised by the live device descriptor. The service follows the device lifetime.', 'values: numeric arguments in descriptor order and units; [] for a no-argument command.', 'success, message and response_json: firmware acknowledgment, not physical completion.'],
    'axiom_interfaces/srv/Connect': ['Opens Axiom’s configured device connection. Connection and firmware sensor acquisition are separate steps.', 'device_uri: empty uses the configured target; a nonempty value overrides the target for this connection.', 'success and message: connection outcome.'],
    'axiom_interfaces/srv/Disconnect': ['Closes Axiom’s device connection while leaving its ROS driver running.', 'Empty request.', 'success and message: disconnect outcome.'],
    'axiom_interfaces/srv/GetConnectionState': ['Reads Axiom’s connection state without connecting or changing acquisition.', 'Empty request.', 'connected, device_uri and last_error: current link state and details.'],
    'axiom_interfaces/srv/PublishedDataSubscription': ['Starts or stops periodic firmware sensor packet delivery. This is separate from a ROS topic subscription and each device’s sampling rate.', 'rate_hz: packet delivery rate in Hz; 0 stops delivery.', 'success and message: firmware request outcome.'],
    'axiom_interfaces/srv/SetSampleRate': ['Changes one sensor’s firmware sampling rate. Packet delivery still requires a separate acquisition request.', 'bus and address: inventory identity; address is hexadecimal without 0x. sample_rate_hz: requested sensor rate.', 'success, message and applied sample_rate_hz; poll_interval_us and retained_poll_results describe firmware polling.'],
    'axiom_interfaces/srv/Ping': ['Sends a firmware version request and measures its round-trip time over the active connection.', 'payload_size: optional version-request padding bytes.', 'success, rtt_ms and message: request outcome and elapsed milliseconds.'],
    'axiom_interfaces/srv/RicRestUrl': ['Sends a RICREST URL request over the active Axiom connection. Its effect depends on the firmware path; some paths change configuration.', 'url_path: firmware path; timeout: seconds, 0 uses the default; ws_pcol: empty or the current session framing.', 'success, json_text and message: raw firmware response and outcome.'],
  };
  const triggerNotes = {
    '/marty/connect': 'Connects Marty using the driver’s configured transport and locator. The driver then requests robot telemetry.',
    '/marty/disconnect': 'Closes Marty’s device connection while leaving the ROS driver running.',
    '/marty/stop': 'Requests Marty to stop. It does not disarm an independently running demo controller.',
  };

  function topicDescription(row) {
    if (topicNotes[row.name]) return topicNotes[row.name];
    if (row.name.endsWith('/diagnostics')) return 'Driver health and diagnostic details for troubleshooting connection, acquisition and decoding.';
    if (row.name.endsWith('/visualization/accelerometers')) return 'Two labelled acceleration arrows derived from the selected Axiom and Marty IMU topics. The origins are display offsets, not measured mounting transforms.';
    if (row.name.endsWith('/visualization/markers')) return 'RViz display markers derived from sensor measurements by the marker adapter.';
    if (row.name.startsWith('/axiom/bus_')) {
      if (row.name.endsWith('/imu/data_raw')) return 'Decoded Axiom IMU acceleration and angular velocity in SI units. Acceleration includes gravity; this adapter does not estimate orientation.';
      if (row.name.endsWith('/range')) return 'Axiom distance measurement in metres. A topic can be discovered before it has a valid reading; NaN means an invalid distance.';
      if (row.name.endsWith('/sample')) return 'Decoded Axiom sensor values with their units, validity, identity and acquisition/receipt timing.';
      if (row.name.endsWith('/data')) return 'Decoded Axiom sensor values as JSON, for profiles that do not need a standard ROS message adapter.';
    }
    return row.note || 'A ROS topic is a named message stream. Publishers send typed messages and subscribers receive compatible messages. Inspect the message definition to understand this interface’s fields.';
  }

  function recipe(kind, row, {reference = false, direction = '', node = ''} = {}) {
    const types = row.types || (row.type ? [row.type] : []), details = [];
    const detail = (name, description) => details.push({name, description});
    let description, command;
    detail('Interface type', types.join(', ') || 'Chosen by the user');
    if (kind === 'topic') {
      description = topicDescription(row);
      command = row.name.startsWith('/') ? 'ros2 topic info ' + quote(row.name) + ' --verbose' : '';
      if (node && direction) detail('Role', node + ' ' + (direction === 'publisher' ? 'publishes this topic.' : 'subscribes to this topic.'));
      for (const type of types) {
        if (fields[type]) detail('Message fields', fields[type]);
        detail('Message definition', 'ros2 interface show ' + quote(type));
      }
      for (const [role, label] of [['publisher', 'Publishers'], ['subscriber', 'Subscribers']]) {
        if (row[role + 's']) detail(label, row[role + 's'].join(', ') || (reference ? 'None in this reference.' : 'None discovered.'));
        for (const endpoint of row[role + '_endpoints'] || []) detail(role === 'publisher' ? 'Publisher QoS' : 'Subscriber QoS', endpoint.node + ' · ' + endpoint.reliability + ' · ' + endpoint.durability);
      }
      const endpoints = [...row.publisher_endpoints || [], ...row.subscriber_endpoints || []];
      if (endpoints.length) detail('QoS meaning', 'RELIABLE retries delivery; BEST_EFFORT permits drops. A reliable subscriber cannot match a best-effort publisher. TRANSIENT_LOCAL retains messages for compatible late subscribers; VOLATILE requests live messages.');
      else if (row.retained) detail('Durability', 'The project reference expects a retained message for compatible transient-local subscribers. Inspect the running endpoints for their actual QoS.');
      detail(reference ? 'Availability' : 'Discovery', reference ? 'This is a possible project interface. Its publisher must be started; sensor-specific topics also require a matching profile and explicit acquisition.' : 'Registered endpoints do not prove messages are arriving or measurements are valid. Use topic echo or topic hz from the console to check delivery.');
      if (row.name.includes('bus_BUS') || row.name.includes('device_ADDRESS')) detail('Sensor identity', 'Replace BUS and ADDRESS with the actual bus/address from /axiom/devices and the discovered topic list.');
    } else if (kind === 'service') {
      let notes = types.map(type => serviceNotes[type]).find(Boolean);
      if (!notes && types.includes('std_srvs/srv/Trigger')) notes = [triggerNotes[row.name] || 'A request/response operation offered by a ROS node. The operation depends on this service’s server.', 'Empty request.', 'success and message: server-reported outcome.'];
      if (!notes && types.includes('std_srvs/srv/SetBool')) notes = ['A boolean request/response operation. Its effect depends on the service server.', 'data: boolean requested state.', 'success and message: server-reported outcome.'];
      description = notes?.[0] || 'A ROS service handles one typed request and returns one response. Discovery shows the interface exists; it does not call the operation or establish device readiness.';
      if (notes) { detail('Request', notes[1]); detail('Response', notes[2]); }
      command = types.length === 1 ? 'ros2 interface show ' + quote(types[0]) : 'ros2 service type ' + quote(row.name);
      detail('Inspect from the console', types.length === 1 ? 'The command prints the interface definition without calling the service. Fields before --- are the request; fields after it are the response.' : 'The command asks discovery for the service type without calling the service. Inspect that type with ros2 interface show.');
      if (row.descriptor) {
        const d=row.descriptor;
        if(d.desc)description=d.desc;
        detail('Descriptor command',d.n);
        if(d.n==='_conf.rate')detail('Arguments','One sampling rate in Hz from the allowed values. The driver applies the firmware configuration map, including polling settings.');
        else if(d.t)detail('Numeric encoding',d.t);
        if(d.r)detail('Allowed range',d.r.join(' to '));
        if(d.map)detail('Allowed values',Object.keys(d.map).sort((a,b)=>Number(a)-Number(b)).join(', '));
        if(d.d!==undefined)detail('Default',String(d.d));
        if(d.f==='LEDPIX')detail('Arguments','Pixel index, red, green, blue. Grid: '+d.NX+' × '+d.NY+'.');
        if(d.mul!==undefined)detail('Scaling','The driver applies descriptor scaling after validating the requested value.');
      }
      if (row.role) detail('Role', row.role);
    } else {
      description = types.includes('marty_interfaces/action/Motion') ? 'Marty’s motion action accepts a goal, reports progress and returns a result. The firmware generates the gait; the driver admits one goal at a time.' : 'A ROS action accepts a goal, supplies ongoing feedback and returns a result. Goals can be cancelled.';
      command = types.length === 1 ? 'ros2 interface show ' + quote(types[0]) : 'ros2 action info ' + quote(row.name);
      if (types.includes('marty_interfaces/action/Motion')) {
        detail('Goal', 'command: walk, dance, kick, stand or move joint; other fields configure steps, side, turn, duration and joint angle. Read the interface for constants and limits.');
        detail('Feedback', 'phase, elapsed_seconds, moving and queued_movements report progress.');
        detail('Result', 'success and message. Completion requires fresh post-command status indicating an idle, empty queue.');
      }
      if (row.role) detail('Role', row.role);
      detail('Inspect from the console', 'The command inspects the action without sending a goal or moving Marty.');
    }
    return {title: (kind[0].toUpperCase() + kind.slice(1)) + ' · ' + row.name, command,
      help: {description, arguments: details, section: 'Details'}, note: row.note || ''};
  }
  function button(kind, row, context) { return root.CommandInfo.button(recipe(kind, row, context)); }
  const api = {recipe, button};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.InterfaceInfo = api;
})(typeof window === 'undefined' ? null : window);
