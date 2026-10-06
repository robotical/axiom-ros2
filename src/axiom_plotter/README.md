# axiom_plotter

`axiom_plotter` is a ROS 2 Python package that subscribes to topics published by the Axiom system and visualizes them in real time as dynamic graphs.

It was designed to complement [`axiom_driver`](../axiom_driver) by providing a lightweight, customizable plotting tool that automatically discovers topics and subscribes to numeric data streams.

---

## Features

- 🔍 **Dynamic topic discovery** — new topics matching a regex filter are auto-subscribed.
- 📈 **Real-time plotting** using `matplotlib` .
- 🔢 **Supports multiple message types:**
  - Standard numeric types (`std_msgs/Float32`, `Int32`, etc.)
  - Common sensor types (`sensor_msgs/Range`)
  - User-specified fields from complex messages (e.g. `pose.position.z` from `PoseStamped`)
- ⚡ **QoS options** for high-rate sensor topics (`--sensor-qos`).
- ⏱ Adjustable history window and refresh rate.

---

## Installation

Make sure you are in the root of your ROS 2 workspace:

```bash
cd ~/Projects/axiom-ros2
colcon build --symlink-install --packages-select axiom_plotter
source install/setup.bash
```

Dependencies are declared in `package.xml`. On Ubuntu/Debian with ROS 2 installed, most should already be present:

```bash
sudo apt install python3-matplotlib python3-numpy
```

---

## Usage

### Launch file

To start the dynamic grapher with default settings:

```bash
ros2 launch axiom_plotter plot_dynamic.launch.py
```

This will:
- Subscribe to all topics containing `/axiom/` in their name
- Plot the last 120 seconds of data
- Update the plot at 15 Hz
- Use sensor-friendly QoS

### Direct run with CLI options

```bash
ros2 run axiom_plotter dynamic_grapher \
  --topic-regex "/axiom/bus_1/device_129/range$" \
  --sensor-qos --qos-depth 200 \
  --history-sec 60 \
  --rate-hz 10
```

Examples:
- Plot **VL53L4CD range sensor**:
  ```bash
  ros2 run axiom_plotter dynamic_grapher \
    --topic-regex "/axiom/bus_1/device_129/range$"
  ```
- Plot **IMU Z acceleration**:
  ```bash
  ros2 run axiom_plotter dynamic_grapher \
    --topic-regex "/axiom/bus_1/device_76a/imu/data_raw$" \
    --field linear_acceleration.z
  ```

---

## CLI Options

| Option               | Default  | Description |
|----------------------|----------|-------------|
| `--topic-regex`      | `""`     | Regular expression searched in topic names (empty = all) |
| `--field`            | `""`     | Dot-path to a numeric field inside complex messages (e.g. `pose.position.z`) |
| `--discovery-interval` | `2.0`  | How often (sec) to check for new topics |
| `--history-sec`      | `60.0`   | Time window to plot (seconds) |
| `--rate-hz`          | `10.0`   | Plot refresh rate (Hz) |
| `--sensor-qos`       | *off*    | Use BEST_EFFORT QoS (better for fast sensors) |
| `--qos-depth`        | `50`     | Queue depth for subscriptions |

---

## Development

- All Python source lives under `axiom_plotter/axiom_plotter/`.
- Main entry point: `dynamic_grapher.py`.
- Launch files: `axiom_plotter/launch/`.

To test changes without rebuilding every time:
```bash
colcon build --symlink-install --packages-select axiom_plotter
source install/setup.bash
```

---

## Future improvements

- [ ] Switch to `pyqtgraph` for smoother high-rate plotting
- [ ] Allow multiple fields per topic (e.g. IMU x/y/z at once)
- [ ] Add parameter YAML support for launch configuration
- [ ] Export plots to file (`.png` or `.csv`) on exit

---

## License

MIT © 2025

History is measured in seconds using message stamps (receipt time if absent), not
GUI frames. Idle data expires and clock resets clear history. `--max-points` defaults
to 100000 per topic to bound memory; reduce the window or increase this cap if needed.
