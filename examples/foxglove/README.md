# Foxglove sensor dashboards

Import [two-axiom-imu.json](two-axiom-imu.json) to view two Axioms without
configuring individual series in the GUI. It works with either USB or Wi-Fi
connections through the host ROS driver.

The layout has four plots:

| Position | Board | Measurement |
|---|---|---|
| Top left | Axiom 1 | X/Y/Z acceleration, m/s² |
| Bottom left | Axiom 1 | X/Y/Z angular velocity, rad/s |
| Top right | Axiom 2 | X/Y/Z acceleration, m/s² |
| Bottom right | Axiom 2 | X/Y/Z angular velocity, rad/s |

All plots use a rolling 30-second window, automatic vertical scaling, and the
same axis colours: X red, Y green, Z blue. They use Foxglove's log/receipt time;
aligning their time axes does not synchronise the boards' hardware clocks.

## Required topics

The driver must already be connected and acquiring measurements on both boards:

```text
/axiom1/imu/data_raw   sensor_msgs/msg/Imu
/axiom2/imu/data_raw   sensor_msgs/msg/Imu
```

Use `axiom1` and `axiom2` as the board keys in `config/boards.yaml`, with this
alias in each board entry:

```yaml
    topic_aliases:
      imu/data_raw: {type: LSM6DS, source: imu/data_raw}
```

An alias requires exactly one matching online sensor. If you have multiple IMUs
on one board, select the intended sensor with the alias's `bus` and `address`
preferences; see the [driver README](../../src/axiom_driver/README.md).
For other namespaces or identity-based topics, replace the topic prefixes in
the layout JSON before importing it. The layout itself does not configure
connections or start acquisition.

## Start the bridge

Keep the driver running. In another terminal, from the repository root:

```bash
source scripts/setup_env.sh
sudo apt install "ros-${ROS_DISTRO}-foxglove-bridge"
ros2 launch foxglove_bridge foxglove_bridge_launch.xml
```

In a pane opened by `scripts/ros_tmux.sh`, the environment is already loaded.
Skip installation if the bridge is installed. The driver and bridge must use
the same ROS domain and middleware settings. No additional build is needed for
the JSON layout.

## Connect the viewer and import

Use the Foxglove desktop app or open [app.foxglove.dev](https://app.foxglove.dev)
in Chrome. Connect using **Foxglove WebSocket**:

- Viewer running on the Pi: `ws://localhost:8765`.
- Viewer running on another computer: `ws://PI_IP:8765`, using the Pi's address.

The browser viewer needs internet access to load and sign in; the direct sensor
stream stays on the local machine or network. See Foxglove's
[connection documentation](https://docs.foxglove.dev/docs/visualization/connecting/live)
and [standalone offline licensing](https://docs.foxglove.dev/docs/standalone-license).

With the viewer connected:

1. Click the current layout name and dropdown arrow in the top toolbar, beside
   the connection address. This opens the **Layouts** menu.
2. Choose **Import from file...** and select
   `examples/foxglove/two-axiom-imu.json` from your local checkout.
3. Name the layout **Axiom: two IMUs** if prompted, and save it for reuse.

If the checkout is on a different computer, copy the JSON to the Pi first:

```bash
# Run on the computer holding this repository, replacing USER and PI_IP.
scp examples/foxglove/two-axiom-imu.json USER@PI_IP:~/two-axiom-imu.json
```

Then import `two-axiom-imu.json` from the Pi user's home directory instead.
See Foxglove's [layout import/export documentation](https://docs.foxglove.dev/docs/visualization/layouts).

### Update an imported layout

Copy the updated JSON to the Pi again, then use **Layouts → Import from file...**
and select that file. Open the newly imported layout and save it for reuse.
Replacing the file on disk does not update an existing saved Foxglove layout.
You can keep the previous layout while checking the updated one.

The four panel headers should read **Axiom 1: Acceleration**,
**Axiom 1: Gyroscope**, **Axiom 2: Acceleration**, and **Axiom 2: Gyroscope**.
In this exported layout format, header titles are stored as `foxglovePanelTitle`
in each panel's configuration.

## Check the plots

Leave both the driver and bridge running. At rest, acceleration includes gravity
(approximately 9.8 m/s² in total), and angular velocity should be near zero.
Tilting a board shifts the gravity components between acceleration axes;
rotating it produces gyroscope changes. Each column should respond to its own
board. These are raw sensor-axis measurements, not fused orientation or speed.

If a plot is empty, check that its topic has a publisher:

```bash
ros2 topic info /axiom1/imu/data_raw
ros2 topic info /axiom2/imu/data_raw
```

A missing alias can mean acquisition is stopped, the IMU is disconnected, or
the alias matches more than one sensor. Compare with `ros2 topic list -t` and
the board's `devices` inventory before changing the layout.

Stop the bridge with `Ctrl+C` in its terminal when finished. This does not stop
the driver or acquisition.

## Thermal and distance heatmaps

Import [two-axiom-heatmaps.json](two-axiom-heatmaps.json) for four Image panels:

| Position | Board | Measurement | Colour scale |
|---|---|---|---|
| Top left | Axiom 1 | AMG8833 thermal grid | 15–40 °C |
| Bottom left | Axiom 1 | VL53L5CX distance grid | 0–4 m |
| Top right | Axiom 2 | AMG8833 thermal grid | 15–40 °C |
| Bottom right | Axiom 2 | VL53L5CX distance grid | 0–4 m |

The layout uses the Image panel's Turbo colour map with fixed limits, so colour
has the same meaning on both boards and does not change when the scene changes.
Low values are blue and high values red; invalid distance zones appear black.
These are native 4×4/8×8 measurements, with no additional image interpolation.
The depth scale is measured range from each sensor zone, not calibrated optical
Z-depth or a 3D point cloud. The image data remains in the firmware's zone order;
use the panel's rotation/flip controls if the physical mounting requires it.
Foxglove's [Image panel documentation](https://docs.foxglove.dev/docs/visualization/panels/image)
describes float images, colour maps and NaN display.

### Board configuration

Add the following entries to the existing `topic_aliases` mapping for each board
in `config/boards.yaml`, preserving its connection settings and existing aliases:

```yaml
    topic_aliases:
      imu/data_raw: {type: LSM6DS, source: imu/data_raw}
      thermal/image: {type: AMG8833, source: thermal/image}
      range/image: {type: VL53L5CX, source: range/image}
```

Use board keys `axiom1` and `axiom2`. Each alias requires one matching online
sensor on that board; add `bus` and `address` selectors if the match is ambiguous.
Both sensors do not need to be attached to both boards: an unattached sensor's
panel will have no data. Each connected sensor retains its identity-based topic
alongside the alias. Verify the aliases after restarting the driver and starting
acquisition:

```bash
ros2 topic list -t | grep -E '/axiom[12]/(thermal|range)/image'
```

All four available topics should have type `sensor_msgs/msg/Image`. A thermal
image contains temperatures in °C; a range image contains distances in metres.
The VL53L5CX requires firmware advertising its multizone profile, such as
`v0.1.19-devlib-host`. Installing the layout alone does not add firmware support.

### Build and import on the Pi

Once the updated repository files are on the Pi, stop the running host driver,
then rebuild from the repository root:

```bash
cd ~/axiom-ros2
source scripts/setup_env.sh
colcon build --base-paths src --symlink-install
source scripts/setup_env.sh
```

Restart the driver with your board configuration and resume acquisition. Keep
the Foxglove bridge running as described above, then select **Layouts → Import
from file...** and choose `examples/foxglove/two-axiom-heatmaps.json`. Save it as
**Axiom: thermal and distance heatmaps**. The temperature panels should show
8×8 pixels; distance panels should show the configured 4×4 or 8×8 grid.
Colour settings and topic selections are already included in the file.

To copy just the layout from another computer, run there:

```bash
scp examples/foxglove/two-axiom-heatmaps.json USER@PI_IP:~/two-axiom-heatmaps.json
```

Import the copied file from the Pi user's home directory. The layout also needs
the updated host driver for the new Image topics. Reimporting the JSON creates a
new layout; replacing a file on disk does not refresh a saved layout.

### Validation limits

Automated tests use the released firmware descriptors and synthetic sensor
frames through two independent firmware peers and real ROS image subscribers.
They check byte layout, units, negative temperatures, status masking, 4×4 padding,
board isolation, aliases and publisher removal. They do not establish physical
VL53L5CX operation, mounting orientation or rendering in the Pi's Foxglove viewer.
