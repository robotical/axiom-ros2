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

## Thermal camera on one Axiom

Import [one-axiom-thermal.json](one-axiom-thermal.json) for one Image panel showing
an AMG8833 thermal camera on `/axiom1/thermal/image`. Its title is **Axiom 1:
Thermal (°C)**. The panel uses the Turbo colour map with a fixed 15–40 °C scale;
low values are blue and high values red. The image contains the sensor's native
8×8 measurements. It preserves the firmware pixel order; use the panel's
rotation/flip controls if your physical mounting requires it.

### Board configuration

Add the following entry to the existing `topic_aliases` mapping for board
`axiom1` in `config/boards.yaml`, preserving its connection settings and other
aliases:

```yaml
    topic_aliases:
      thermal/image: {type: AMG8833, source: thermal/image}
```

The alias requires exactly one matching online AMG8833. Add `bus` and `address`
selectors if the match is ambiguous. The driver also preserves the camera's
identity-based topic. If you use another board namespace, select its thermal
image topic in the panel's settings after importing the layout.

### Update and start on the Pi

Stop the running host driver before rebuilding, then run from the repository:

```bash
cd ~/axiom-ros2
git pull --ff-only origin main
source scripts/setup_env.sh
colcon build --base-paths src --symlink-install
source scripts/setup_env.sh
```

The layout is JSON; rebuilding is only needed to pick up the host driver changes
if you have not built them yet. Updating an already-built layout needs just the
Git pull and import.

Run the driver for the selected board in one terminal:

```bash
ros2 launch axiom_driver axiom_minimal_launch.py namespace:=axiom1 \
  boards_file:="$HOME/axiom-ros2/config/boards.yaml"
```

In another terminal with the same environment loaded, connect and acquire:

```bash
ros2 service call /axiom1/connect axiom_interfaces/srv/Connect '{device_uri: ""}'
ros2 service call /axiom1/publish_data_subscription \
  axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 20.0}'
ros2 topic info /axiom1/thermal/image
```

The services should return `success: true`; the topic should have type
`sensor_msgs/msg/Image` and one publisher. The sensor must be attached and its
firmware profile enabled. In another terminal, start the bridge:

```bash
ros2 launch foxglove_bridge foxglove_bridge_launch.xml
```

### Import and check

Connect Foxglove to `ws://localhost:8765` on the Pi. Select **Layouts → Import
from file...** and choose `examples/foxglove/one-axiom-thermal.json`. Save it as
**Axiom: thermal camera**. Importing the new file replaces neither the contents
nor the selected panel of an older saved layout; open the newly imported layout.

You should see one thermal panel. Move your hand in front of the camera and
check that warmer pixels change colour. The topic, colour map and scale are
already configured. See Foxglove's [Image panel documentation](https://docs.foxglove.dev/docs/visualization/panels/image)
for display settings.

To copy just the layout from another computer, run there:

```bash
scp examples/foxglove/one-axiom-thermal.json USER@PI_IP:~/one-axiom-thermal.json
```

Import the copied file from the Pi user's home directory.

### Validation limits

The single-panel JSON configuration is validated against the official Foxglove
SDK. The host image output has automated tests using the released AMG8833
metadata, synthetic thermal frames and real ROS image subscribers, including
negative temperatures, units, timestamps and aliases. Physical mounting
orientation and rendering/import in the Pi's Foxglove viewer remain unverified.
