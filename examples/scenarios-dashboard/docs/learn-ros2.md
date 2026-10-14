# Console workflow and ROS concepts

For setup, use the [repository README](../../../README.md). For the optional
browser guide and its ready-to-copy scenarios, use the
[dashboard README](../README.md). A running driver does not imply a connected
board or active acquisition.

Ordinary single-board scenarios are manual:

1. Start the driver in Terminal 1 and leave it running.
2. Call its connection service in Terminal 2.
3. Request Axiom firmware acquisition separately.
4. Inspect devices, topics, services and actual measurements.
5. Start an optional visualiser in Terminal 3 and RViz in Terminal 4.
6. Stop viewers, stop acquisition, disconnect, then stop the driver.

The USB + Wi-Fi scenario explicitly opts into automatic connection/acquisition
through its generated file. Review its endpoints and startup flags first.
An echo creates a ROS subscriber; it does not configure sensors or start delivery.
Hot swapping a supported sensor while its board remains connected restores
measurements without another request. Reconnecting the board itself with manual
settings needs a new acquisition call.

## Names and state

- A node is a running ROS process component.
- A topic has publishers/subscribers; discovery alone does not confirm valid data.
- A service carries one request and response; a descriptor command's success means
  firmware acknowledgement, not physical completion of actuator motion.
- An action provides a goal, feedback and result; Axiom descriptor commands use
  services rather than actions.
- The inventory describes module identity, availability, metadata and commands.
- Identity topics include firmware bus and hexadecimal address. Copy discovered
  paths rather than inferring addresses from connector numbers.
- Aliases preserve identity topics and bind only to one matching online sensor.

Use Best Effort subscriptions for the default sensor publishers and Transient
Local durability to receive retained inventory. All ROS processes need the same
domain and compatible middleware settings. Sensor sample rate and firmware
delivery rate are separate settings.

## Consoles and cleanup

The [shared tmux helper](../../../docs/tmux.md) opens four empty consoles and loads
the environment in new panes. Ctrl+b, release, then an arrow switches panes;
z zooms and d detaches. Rerun `bash scripts/ros_tmux.sh` from the repository root
to reattach. On the Ubuntu terminal, Shift+drag selects text, Ctrl+Shift+C copies,
and Ctrl+Shift+V pastes.

Detach preserves processes. For cleanup, use each running driver's acquisition
and disconnect services before stopping it. A **Start from scratch** control
exists only with an optional reset adapter and is not required for native Linux.
