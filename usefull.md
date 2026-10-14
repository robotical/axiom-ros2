# Axiom ROS 2 command reference

For setup and configuration, use the [README](README.md) and
[published user guides](https://userguides.robotical.io/axiom/ros2/start).
Prepare each Bash terminal from the repository root with
`source scripts/setup_env.sh`, or use the [tmux helper](docs/tmux.md).
The examples use `/axiom`; substitute your configured namespace.

## Start and acquire

Terminal 1:

```bash
ros2 launch axiom_driver axiom_minimal_launch.py \
  namespace:=axiom boards_file:="$AXIOM_ROS_BOARDS_FILE"
```

Terminal 2:

```bash
ros2 service call /axiom/connect axiom_interfaces/srv/Connect '{device_uri: ""}'
ros2 service call /axiom/publish_data_subscription \
  axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 20.0}'
ros2 node list --no-daemon
ros2 topic list -t --no-daemon
ros2 service list -t
ros2 topic echo /axiom/devices --qos-durability transient_local --once
```

Connect uses the USB or framed `/ws` endpoint in the board file. Check `success`
in each response; delivery rate is separate from sensor sampling rate.

## Inspect and stop

Replace the placeholder with the exact discovered topic:

```bash
SENSOR_TOPIC='PASTE_DISCOVERED_SENSOR_TOPIC_HERE'
ros2 topic echo "$SENSOR_TOPIC" --qos-reliability best_effort --once
ros2 topic info "$SENSOR_TOPIC" --verbose
```

For firmware version over the active driver connection:

```bash
ros2 service call /axiom/ric_rest_url axiom_interfaces/srv/RicRestUrl \
  '{url_path: "v", timeout: 3.0, ws_pcol: ""}'
```

Stop viewers/echoes, then stop acquisition and disconnect before stopping the driver:

```bash
ros2 service call /axiom/publish_data_subscription \
  axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 0.0}'
ros2 service call /axiom/disconnect axiom_interfaces/srv/Disconnect '{}'
```

More workflows: [sensor services and multiple boards](docs/sensors-and-boards.md),
[thermal RViz](docs/thermal-camera.md), and [Foxglove](examples/foxglove/README.md).
