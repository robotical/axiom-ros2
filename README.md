# Axiom ROS 2

Connect an Axiom over USB or Wi-Fi and read its LSM6DS accelerometer in ROS 2.

## 1. Set up and build

Use Ubuntu 24.04, ROS 2 Jazzy and a Bash terminal. Install ROS using the
[Ubuntu installation instructions](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html),
then install the build tools:

```bash
sudo apt install ros-dev-tools
sudo rosdep init  # Only once per machine; skip if already initialized.
rosdep update
```

From the `axiom-ros2` repository root:

```bash
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --base-paths src --symlink-install
```

## 2. Configure this machine and Axiom

Create the local configuration files on first setup. Both are ignored by Git:

```bash
cp -n config/machine.env.example config/machine.env
cp -n config/boards.yaml.example config/boards.yaml
```

`config/machine.env` sets the ROS installation, DDS domain and board file:

```bash
ROS_SETUP_FILE=/opt/ros/jazzy/setup.bash
ROS_DOMAIN_ID=0
AXIOM_ROS_BOARDS_FILE="$AXIOM_ROS_ROOT/config/boards.yaml"
```

The workspace defaults to this checkout. Set `ROS_WORKSPACE` if you built in
another workspace, or change `ROS_SETUP_FILE` if ROS is installed elsewhere.
Use the same `ROS_DOMAIN_ID` in all ROS terminals.

For **USB**, set `config/boards.yaml` to:

```yaml
axioms:
  axiom:
    transport: serial
    serial.port: /dev/serial/by-id/REPLACE_WITH_AXIOM_DEVICE
    auto_connect: false
    auto_reconnect: false
    autosub: false
    topic_aliases:
      imu/data_raw: {type: LSM6DS, source: imu/data_raw}
```

Find the USB path with `ls -l /dev/serial/by-id/`. If access is denied, run
`sudo usermod -aG dialout "$USER"`, then log out and back in.

For **Wi-Fi**, replace the `transport` and `serial.port` lines inside the same
board entry with:

```yaml
    transport: ws
    device_uri: ws://192.168.1.3/ws
```

Use Axiom's actual IP address; it must already be connected to your Wi-Fi network.

The alias gives one LSM6DS sensor the name `/axiom/imu/data_raw` for this example.
Sensors are discovered automatically; the YAML is not a required sensor list.

Driver defaults are in [src/axiom_driver/config/axiom.yaml](src/axiom_driver/config/axiom.yaml).
Values in `boards.yaml` override those defaults; explicit launch arguments override both.

### Optional tmux consoles

Keep the driver, service commands and viewers in one terminal window with four panes:

```bash
sudo apt install tmux
bash scripts/ros_tmux.sh
```

Run this from the repository root after configuring `machine.env` and `boards.yaml`.
Each pane loads the ROS installation and built workspace through `scripts/setup_env.sh`.
The panes start empty; run the commands below manually. The helper works with the core
packages alone, including when the dashboard example is not built.

Press `Ctrl+b`, release both keys, then an arrow to switch panes. `Ctrl+b`, then `d`
detaches while commands continue running. Run `bash scripts/ros_tmux.sh` again to reattach.
`Ctrl+C` stops the foreground command in the selected pane. The helper and its
`console.bashrc` and `tmux.conf` live together in `scripts/`.

## 3. Connect and read acceleration

Run these commands from the repository root. In **Terminal 1**, prepare the
environment and start the driver:

```bash
source scripts/setup_env.sh
ros2 launch axiom_driver axiom_minimal_launch.py namespace:=axiom
```

The setup script loads `machine.env` and the built workspace. The launch reads
`boards.yaml` through `AXIOM_ROS_BOARDS_FILE`. Keep this terminal running;
connection and acquisition are manual.

In **Terminal 2**, connect, request measurements, then display acceleration:

```bash
source scripts/setup_env.sh
ros2 service call /axiom/connect axiom_interfaces/srv/Connect '{device_uri: ""}'
ros2 service call /axiom/publish_data_subscription axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 20.0}'
ros2 topic echo /axiom/imu/data_raw --field linear_acceleration --qos-reliability best_effort
```

Both services should return `success: true`. The empty `device_uri` uses the
connection in `boards.yaml`. The echo prints `x`, `y` and `z` in m/s², including
gravity. Move Axiom to see the readings change.

If no readings appear, stop the echo with Ctrl+C and run `ros2 topic list -t`.
The discovered sensor also has a topic ending in
`/bus_<bus>/device_<address>/imu/data_raw`; you can echo that path directly.

## 4. View acceleration in RViz

Leave the driver and acquisition running. In **Terminal 3**, from the repository
root, build the optional visualization example:

```bash
source scripts/setup_env.sh
rosdep install --from-paths src examples/scenarios-dashboard/src/axiom_marty_demo --ignore-src -r -y
colcon build --base-paths src examples/scenarios-dashboard/src/axiom_marty_demo \
  --packages-select axiom_marty_demo --symlink-install
source scripts/setup_env.sh
ros2 run axiom_marty_demo sensor_view --ros-args -r __ns:=/sensing -p axiom_namespace:=/axiom
```

Keep this terminal running. The viewer discovers the IMU through `/axiom/devices`
and converts its measurements into RViz markers. It requires neither the dashboard
nor a Marty.

In **Terminal 4**, open RViz with the supplied display configuration:

```bash
source scripts/setup_env.sh
ros2 run rviz2 rviz2 -d "$(ros2 pkg prefix --share axiom_marty_demo)/config/sensors.rviz"
```

The teal arrow shows acceleration, including gravity. Move Axiom to see it change.
The configuration sets the fixed frame to `sensor_view` and subscribes to
`/sensing/visualization/markers`.

### Optional Foxglove dashboard for two Axioms

The [ready-made Foxglove layout](examples/foxglove/two-axiom-imu.json) has
acceleration and gyroscope plots for `/axiom1/imu/data_raw` and
`/axiom2/imu/data_raw`, with X/Y/Z series already configured. See the
[Foxglove setup and import guide](examples/foxglove/README.md) to connect the
viewer and load the layout.

For AMG8833 thermal cameras and VL53L5CX multizone distance sensors, the
[heatmap layout](examples/foxglove/two-axiom-heatmaps.json) provides four Image
panels with temperature and distance colour scales. The host driver publishes
standard float Image messages; see the [heatmap setup guide](examples/foxglove/README.md#thermal-and-distance-heatmaps)
for board aliases, rebuilding and import instructions.

## 5. Stop

Close RViz and press Ctrl+C in Terminal 3 to stop the viewer.

Ctrl+C in Terminal 2 stops the echo. Stop acquisition and disconnect:

```bash
ros2 service call /axiom/publish_data_subscription axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 0.0}'
ros2 service call /axiom/disconnect axiom_interfaces/srv/Disconnect '{}'
```

Then Ctrl+C in Terminal 1 stops the driver.

More parameters and interfaces: [driver README](src/axiom_driver/README.md).
