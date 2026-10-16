# Foxglove sensor dashboards

Use the host ROS driver with either USB or Wi-Fi. Foxglove displays ROS topics
through `foxglove_bridge`; it does not connect directly to Axiom or start firmware
acquisition. Complete the [host setup](../../README.md) first, using host firmware
and the setup-file path for your installed ROS distribution.

Ready-made layouts:

| Layout | Display |
|---|---|
| [one-axiom-thermal.json](one-axiom-thermal.json) | One AMG8833 8×8 thermal Image panel |
| [two-axiom-imu.json](two-axiom-imu.json) | Acceleration and angular velocity plots for two boards |
| [one-axiom-sound.json](one-axiom-sound.json) | All sound scalars and the latest nine-band spectrum, with an embedded user script |

These use example board namespaces. Match those namespaces/aliases in your board
configuration, or select your actual topics in the imported panel settings.
For the sound sensor's alias configuration, script and walkthrough, see
[Sound sensor demo](sound-demo.md).

## Install the bridge and connect a viewer

In a prepared terminal at the repository root, install the bridge once for the
loaded distribution:

```bash
source scripts/setup_env.sh
sudo apt install "ros-${ROS_DISTRO}-foxglove-bridge"
```

Installation uses the ROS package repositories configured for that distribution.
See the [official ROS bridge guide](https://docs.foxglove.dev/docs/getting-started/frameworks/ros2)
for package availability and source-build options. Start the bridge after the
driver is running with the same ROS domain and middleware settings:

```bash
ros2 launch foxglove_bridge foxglove_bridge_launch.xml
```

Leave it running. Open [app.foxglove.dev](https://app.foxglove.dev) in Chrome or the
[Foxglove desktop app](https://foxglove.dev/download) on a supported computer.
Choose **Open connection** from the dashboard or top-left app menu, then
**Foxglove WebSocket**:

- Viewer on the bridge host: `ws://localhost:8765`.
- Viewer on another computer: `ws://ROS_HOST_IP:8765`, replacing `ROS_HOST_IP`
  with the bridge host's reachable address, not Axiom's Wi-Fi address.

Select **Open** and check that the Axiom topics appear. `localhost` means the
computer running the viewer. For a remote viewer, the bridge's TCP port 8765 must
be reachable; browser/OS local-network permissions may also need to be allowed.

You need account access to direct connections and layout import/editing. Foxglove
currently specifies a developer seat for direct connections and editing layouts;
see its [live connection](https://docs.foxglove.dev/docs/visualization/connecting/live)
and [layout](https://docs.foxglove.dev/docs/visualization/layouts) documentation.
The web viewer needs internet to load and sign in. The direct measurement stream
travels between the local bridge and viewer. Desktop offline use depends on
[standalone licensing](https://docs.foxglove.dev/docs/standalone-license).
[RViz](../../docs/thermal-camera.md) provides a local thermal-display alternative.

## Thermal camera on one Axiom

The single-camera layout subscribes to `/axiom1/thermal/image`. Its Image panel
is titled **Axiom 1: Thermal (°C)** and uses Turbo with a fixed **15–40 °C** scale.
Values beyond the colour limits clip to the end colours; ROS measurements retain
their original values. The native 8×8 grid is not an interpolated camera image.

### Update and configure

For an existing clone already on `main` with no local source changes, stop
acquisition, disconnect and stop affected ROS processes before updating. From the
repository root:

```bash
git pull --ff-only origin main
source scripts/setup_env.sh
rosdep install --from-paths src --ignore-src -r -y
colcon build --base-paths src --symlink-install
source scripts/setup_env.sh
```

For first setup, use the [README](../../README.md). A layout-only update needs a
pull and reimport, without a rebuild. Changing driver code requires a rebuild
and restart.

In `config/boards.yaml`, use board key `axiom1` for this example. If renaming the
earlier `axiom` key, stop its driver first, preserve the USB or Wi-Fi settings,
and use automatic startup: remove explicit false overrides for
`auto_connect`, `auto_reconnect` and `autosub`. An identity rule can select the
board without a USB path or IP; see [automatic startup](../../docs/automatic-startup.md). Merge this alias
into the board's existing `topic_aliases` mapping:

```yaml
    topic_aliases:
      thermal/image: {type: AMG8833, source: image}
```

This is a fragment, not a replacement board file. It binds to exactly one online,
resolved and fresh AMG8833; use inventory `bus` and `address` selectors if several
cameras match. An alias names ROS output rather than installing a device profile.
The canonical sensor topic remains available. For another namespace, substitute
it throughout the commands and select its image topic in the panel.

### Start the session

The [tmux helper](../../docs/tmux.md) opens four empty panes with the environment
preloaded. Use Terminal 1 for the driver, Terminal 2 for services/inspection,
Terminal 3 for the bridge, and Terminal 4 for optional checks. In separate windows
or reused panes after a rebuild, source `scripts/setup_env.sh` first.

Terminal 1:

```bash
ros2 launch axiom_driver axiom.launch.py
```

Terminal 2:

```bash
ros2 topic list -t --no-daemon
ros2 topic info /axiom1/thermal/image
ros2 topic echo /axiom1/thermal/image --once --qos-reliability best_effort
```

Discovery connects and acquires automatically. Expect the topic to be
`sensor_msgs/msg/Image` with one publisher. A frame has width/height 8, encoding
`32FC1`, `is_bigendian: 0`, `step: 32`, and 256 bytes representing 64 little-endian
float32 temperatures in °C. Its header has the sample timestamp and sensor frame.
The camera's `grid` topic remains available for RViz.

The camera must be connected with a supported firmware profile. The publication rate
controls delivery, not camera sampling. An echo or viewer alone does not enable
acquisition.

In Terminal 3, run the bridge command from the section above, then connect the viewer.

### Import and check

1. Click the layout name/dropdown in the top toolbar to open **Layouts**.
2. Choose **Import from file...** and select
   `examples/foxglove/one-axiom-thermal.json` on the viewer computer.
3. Open the newly imported layout and save it as **Axiom: thermal camera**.

If the checkout is on another computer, download the
[thermal JSON](https://raw.githubusercontent.com/robotical/axiom-ros2/main/examples/foxglove/one-axiom-thermal.json)
to the viewer computer, or copy it there. For example, run from the checkout on
the source computer, replacing the login/address of the viewer computer:

```bash
scp examples/foxglove/one-axiom-thermal.json USER@VIEWER_HOST:~/one-axiom-thermal.json
```

Import the copied file from the viewer computer's home directory. The supplied
layout has one thermal panel. Move a hand in front of the camera to see warmer
pixels change colour. Pixel order follows firmware; adjust the panel's rotation
or flip controls for mounting. Enlarging the display adds no measured pixels.
This 2D heatmap needs no TF tree or camera calibration. A spatial 3D projection
requires a separate calibration and frame contract.

Replacing a JSON file does not update a saved Foxglove layout. Import it again
and open the new layout after a layout change.

### Troubleshoot and finish

| Symptom | Check |
|---|---|
| No Axiom topics | Driver running, acquisition enabled, matching ROS domain/middleware |
| Viewer cannot connect | Bridge running, correct host address/port, local-network permission and direct-connection entitlement |
| No image publisher | Camera online in `/axiom1/devices`, correct alias/type/namespace |
| Identity image exists, alias absent | Resolve an ambiguous match with bus/address, or select the identity topic |
| Grid exists, image absent | Build/source/restart the current host driver; Image output needs known Celsius units |
| One colour | Inspect temperatures and adjust **Value min** / **Value max** |
| Extra panels | Open the newly imported `one-axiom-thermal.json` layout |

Stop the bridge in Terminal 3. In Terminal 2:

```bash
ros2 service call /axiom1/publish_data_subscription \
  axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 0.0}'
ros2 service call /axiom1/disconnect axiom_interfaces/srv/Disconnect '{}'
```

Then stop the driver. Published walkthrough:
[Thermal camera in Foxglove](https://userguides.robotical.io/axiom/ros2/foxglove).
See the [Image panel documentation](https://docs.foxglove.dev/docs/visualization/panels/image)
for display controls.

## Two-board IMU plots

[two-axiom-imu.json](two-axiom-imu.json) plots X/Y/Z acceleration and angular
velocity for `/axiom1/imu/data_raw` and `/axiom2/imu/data_raw`. Use board keys
`axiom1` and `axiom2`, each with its firmware `id` or explicit endpoint and this alias fragment:

```yaml
    topic_aliases:
      imu/data_raw: {type: LSM6DS, source: data_raw}
```

Each alias needs exactly one matching online IMU; use bus/address selectors if
needed. Follow the [multi-board workflow](../../docs/sensors-and-boards.md#multiple-boards)
with those namespace names and automatic startup. Both boards connect and acquire
automatically; explicit manual control remains available.
Use a single Foxglove bridge for the ROS session.

Import `examples/foxglove/two-axiom-imu.json` on the viewer computer using the
same Layouts menu. For a remote checkout, download the
[IMU JSON](https://raw.githubusercontent.com/robotical/axiom-ros2/main/examples/foxglove/two-axiom-imu.json)
or copy that file to the viewer computer before import.

| Position | Panel title | Units |
|---|---|---|
| Top left | Axiom 1: Acceleration | m/s² |
| Bottom left | Axiom 1: Gyroscope | rad/s |
| Top right | Axiom 2: Acceleration | m/s² |
| Bottom right | Axiom 2: Gyroscope | rad/s |

The plots have a rolling 30-second window, automatic vertical scaling, and X red,
Y green, Z blue. They use log/receipt time; aligned axes do not synchronise hardware
clocks. At rest, acceleration includes about 9.8 m/s² of gravity in total, and
angular velocity should be near zero. Tilt/rotate each board to check its own column.
These are raw sensor-axis values, not fused orientation or speed.

For empty plots, check actual publisher counts, the inventory, acquisition and
alias ambiguity. For different namespaces, select those topics in the panel
settings. Stop the bridge, then stop acquisition and disconnect both drivers
using their respective namespaces before stopping the multi-board launch.

Layout configuration and automated image-output evidence are recorded in
[validation.md](../../docs/validation.md). Those dated checks do not establish
physical mounting orientation or rendering on every workstation.
