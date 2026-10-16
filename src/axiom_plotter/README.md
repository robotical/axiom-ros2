# axiom_plotter

Plot numeric ROS measurements with Matplotlib. The tool discovers matching topics
and subscribes with the selected QoS; it does not connect Axiom or start acquisition.
Complete the [host setup](../../README.md) and leave the driver acquiring. The
core build includes this package and its dependencies. Use a graphical desktop
for the plotting window and the same ROS domain/middleware as the driver.

## Launch defaults

From a prepared terminal at the repository root:

```bash
source scripts/setup_env.sh
ros2 launch axiom_plotter plot_dynamic.launch.py
```

This launch selects topics containing `/axiom/`, a 120-second history, 15 Hz plot
refresh and best-effort QoS. Without an explicit field, only its known scalar
numeric types and scalar Range messages are plotted. Use a direct command below
for IMU fields or other board namespaces.

## Select a scalar range or IMU field

Find exact topics with `ros2 topic list -t --no-daemon`. Replace the placeholders.
For a `sensor_msgs/msg/Range` topic:

```bash
RANGE_TOPIC='PASTE_DISCOVERED_SCALAR_RANGE_TOPIC_HERE'
ros2 run axiom_plotter dynamic_grapher \
  --topic-regex "^${RANGE_TOPIC}$" --sensor-qos \
  --qos-depth 200 --history-sec 60 --rate-hz 10
```

For an IMU's Z acceleration:

```bash
IMU_TOPIC='PASTE_DISCOVERED_IMU_TOPIC_HERE'
ros2 run axiom_plotter dynamic_grapher \
  --topic-regex "^${IMU_TOPIC}$" --field linear_acceleration.z --sensor-qos
```

The regular expression matches the selected topic. Use a suffix such as
`/data_raw$` to compare that field across multiple boards. `--sensor-qos` selects
Best Effort, compatible with the driver's default sensor publishers. The direct
executable defaults to Reliable; include the flag unless publishers are configured
otherwise. IMU acceleration includes gravity in m/s²; angular velocity is rad/s.

## Options

| Option | Direct executable default | Meaning |
|---|---|---|
| `--topic-regex` | Empty | Regex searched in topic names; empty matches all |
| `--field` | Empty | Numeric dot path for other message types, such as `linear_acceleration.z` |
| `--discovery-interval` | 2.0 | Topic discovery interval, seconds |
| `--history-sec` | 60.0 | Plot history, seconds |
| `--rate-hz` | 10.0 | Display refresh, not sensor sampling or firmware delivery rate |
| `--sensor-qos` | Off | Best Effort instead of Reliable |
| `--qos-depth` | 50 | Subscription queue depth |
| `--max-points` | 100000 | Memory cap per topic |

History uses message stamps, falling back to receipt time when no header is present.
Idle history expires, and clock resets clear history. This does not synchronise
board clocks. Stop the plot with Ctrl+C or close its window; driver acquisition
continues until you stop it separately.

For source changes, stop the plot, then rebuild from the repository root:

```bash
source scripts/setup_env.sh
colcon build --base-paths src --packages-select axiom_plotter --symlink-install
source scripts/setup_env.sh
```

Source is under `axiom_plotter/`, with launch files under `launch/` in this package.
For ready-made X/Y/Z plots, see the [Foxglove layouts](../../examples/foxglove/README.md).
