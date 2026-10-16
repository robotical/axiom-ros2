# AMG8833 thermal camera in RViz

Complete the [host-driver setup](../README.md), using a supported AMG8833 profile
and a working USB or Wi-Fi connection. This example uses board key `axiom` and
namespace `/axiom`; substitute another configured namespace throughout if needed.
Use the automatic startup defaults; remove explicit false overrides for
`auto_connect`, `auto_reconnect` and `autosub` in this walkthrough. Attach the camera.

The core build includes `axiom_thermal_viz` and its RViz configuration. The scenarios
dashboard is optional. Run RViz in a graphical desktop session. If rebuilding or
changing configuration, stop acquisition, disconnect and stop affected processes
first. Rebuild from the repository root and reload the workspace:

```bash
source scripts/setup_env.sh
rosdep install --from-paths src --ignore-src -r -y
colcon build --base-paths src --symlink-install
source scripts/setup_env.sh
```

Use the [four-pane tmux helper](tmux.md), or prepare four Bash terminals at the
checkout with `source scripts/setup_env.sh`. Reused panes need that refresh after
a rebuild. If retaining an existing connected/acquiring driver, continue at topic
inspection rather than starting a second driver.

## Terminal 1: driver

```bash
ros2 launch axiom_driver axiom.launch.py
```

Leave it running.

## Terminal 2: inspect

```bash
ros2 topic list -t --no-daemon
```

Discovery connects and starts acquisition automatically. Find the exact `thermal/grid` topic
of type `axiom_interfaces/msg/ThermalGrid` and replace the placeholder:

```bash
THERMAL_TOPIC='PASTE_DISCOVERED_THERMAL_GRID_TOPIC_HERE'
ros2 topic echo "$THERMAL_TOPIC" axiom_interfaces/msg/ThermalGrid \
  --qos-reliability best_effort --once
```

Expect width/height 8, 64 `temperature_c` values and a nonempty `header.frame_id`.
The prompt returns after one frame. Resolve missing data before continuing. The
delivery request does not set the camera's sampling rate; actual frame rate depends
on its sampling configuration. No thermal alias is required for the identity topic.

## Terminal 3: heatmap adapter

Variables belong to the terminal where they are set. Put the same discovered topic
in this terminal, then start the visualiser:

```bash
THERMAL_TOPIC='PASTE_DISCOVERED_THERMAL_GRID_TOPIC_HERE'
ros2 run axiom_thermal_viz thermal_heatmap --ros-args \
  -r __ns:=/sensing -p input_topic:="$THERMAL_TOPIC" \
  -p output_topic:=thermal_heatmap -p use_dynamic_range:=false \
  -p min_temperature:=15.0 -p max_temperature:=40.0
```

Leave it running. It publishes `/sensing/thermal_heatmap` markers and
`/sensing/thermal_heatmap_labels` temperature labels, with a fixed 15–40 °C scale.
Pixel order is retained rather than corrected for physical mounting.

## Terminal 4: frame and RViz

Set the same camera topic in this terminal and read a live frame ID:

```bash
THERMAL_TOPIC='PASTE_DISCOVERED_THERMAL_GRID_TOPIC_HERE'
THERMAL_FRAME="$(ros2 topic echo "$THERMAL_TOPIC" \
  axiom_interfaces/msg/ThermalGrid --field header.frame_id \
  --qos-reliability best_effort --once | sed -n '1p')"
printf '%s\n' "$THERMAL_FRAME"
ros2 run rviz2 rviz2 \
  -d "$(ros2 pkg prefix --share axiom_thermal_viz)/config/thermal.rviz" \
  -f "${THERMAL_FRAME:?No camera frame received}"
```

Run the frame and RViz commands in the same terminal. The display uses a Marker
heatmap and MarkerArray pixel labels. Move a hand near the camera to see changing
temperatures. Cell size is a display layout, not measured object size or position.

For an empty display, check the raw grid, exact input topic, marker publisher and
Fixed Frame. The heatmap can render in its own sensor frame without another TF
node, though RViz can still report no global TF data. A robot-relative display needs
the camera's actual mounting transform. Adjust the colour limits if temperatures
are outside 15–40 °C.

## Finish

Stop RViz and the adapter with Ctrl+C. In Terminal 2:

```bash
ros2 service call /axiom/publish_data_subscription \
  axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 0.0}'
ros2 service call /axiom/disconnect axiom_interfaces/srv/Disconnect '{}'
```

Then stop the driver. See [visualiser parameters](../src/axiom_thermal_viz/README.md)
or the [Foxglove Image alternative](../examples/foxglove/README.md#thermal-camera-on-one-axiom).
Published walkthrough: [Thermal camera in RViz](https://userguides.robotical.io/axiom/ros2/thermal_camera).
