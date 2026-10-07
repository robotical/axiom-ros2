# Console workflow

Use the Scenarios tab for the complete sequence. Every step is manual; a ROS
driver being present does not imply a connected device or active acquisition.

1. Start a driver in Terminal 1. It stays running until Ctrl+C.
2. Call its connection service in Terminal 2.
3. For Axiom, request firmware acquisition separately.
4. Inspect devices, topics and services. New supported modules are discovered
   without restarting the driver or sending another acquisition request.
5. Run `ros2 topic echo` in another terminal. This creates a ROS subscriber; it
   does not configure the sensor or start firmware delivery.
6. Start a marker adapter and RViz when you want a visual display.
7. Stop acquisition, disconnect, then stop the driver when finished.

For the ready-to-copy commands, see the [project README](../README.md).

## Names and state

- A node is a running ROS process component.
- A topic has publishers and subscribers. Discovery describes their registration,
  not whether valid messages are arriving.
- A service takes one request and returns one response.
- An action accepts a goal and provides feedback and a result.
- The Axiom inventory describes module identity, availability, descriptor
  readiness, aliases and supported commands.
- Identity-based sensor topics include bus and extended hexadecimal address.
- An optional alias gives a sensor a stable topic name for subscribers and RViz.
  It is withheld when no device or several devices match its rule.

The dashboard's information buttons explain message fields, service requests,
command arguments and QoS. Best Effort subscribers match the sensor publishers;
Transient Local lets inventory subscribers receive the retained inventory.

## Consoles

The supplied workstation has four tmux panes. Press Ctrl+b, release it, then an
arrow key to switch panes. Ctrl+C affects only the selected pane. Ctrl+b then d
detaches; from the repository root, run
`bash examples/scenarios-dashboard/scripts/ros_tmux.sh` again to reattach. Ctrl+Shift+V pastes in
the Linux terminal. Shift+mouse selection bypasses tmux's mouse handling.

Use **Start from scratch** to end the current workstation session. All drivers,
connections, acquisition requests and viewers then need to be started again.
