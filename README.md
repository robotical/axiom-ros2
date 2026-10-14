# Axiom ROS 2

Connect Axiom to a Linux computer over USB or Wi-Fi and use its sensors in ROS 2.
The **host driver runs on that computer**. It discovers supported connected devices,
publishes measurements as ROS topics, and exposes descriptor-defined configuration
and output commands as ROS services. A compatible Raspberry Pi can serve as the
host just as a desktop computer can.

Use the current **host firmware** variant from the
[Axiom updater](https://updates.robotical.io). It must recognise the connected
sensors and supply their descriptors; see the
[Device Library guides](https://userguides.robotical.io/axiom/device_library/start)
to manage profiles. Native ROS/Zenoh firmware is a separate option and is not needed
for this workflow. With normal DDS-based ROS middleware, no Zenoh router is required.
If you select another middleware, follow its own setup instructions.

The examples use user-chosen namespaces and illustrative addresses. Replace paths,
addresses and discovered sensor topics with the values for your hardware. Run one
firmware acquisition client per Axiom and let other consumers subscribe to its ROS
topics.

The [published user guides](https://userguides.robotical.io/axiom/ros2/start) cover
the same workflow. Repository walkthroughs:

- [tmux consoles and clipboard controls](docs/tmux.md)
- [Sensor discovery, aliases, reconnecting and multiple boards](docs/sensors-and-boards.md)
- [AMG8833 thermal camera in RViz](docs/thermal-camera.md)
- [Foxglove thermal heatmap and two-board IMU plots](examples/foxglove/README.md)
- [Optional scenarios dashboard](examples/scenarios-dashboard/README.md)
- [Driver parameters and interface contracts](src/axiom_driver/README.md)

## 1. Install and build

The installation example uses **Ubuntu 24.04, ROS 2 Jazzy and Bash**. Install ROS
first using the [official Ubuntu instructions](https://docs.ros.org/en/jazzy/Installation/Ubuntu-Install-Debs.html),
including its package repositories. If using another compatible ROS distribution,
follow its installation instructions and substitute its setup path below. Use one
distribution per terminal and build workspace.

Install Git and the build tools:

```bash
sudo apt update
sudo apt install git ros-dev-tools
sudo rosdep init  # Once per machine; skip if already initialized.
rosdep update
```

Choose a writable directory for the checkout. For an existing clone, change to its
root and skip the clone commands:

```bash
git clone https://github.com/robotical/axiom-ros2.git
cd axiom-ros2
source /opt/ros/jazzy/setup.bash
rosdep install --from-paths src --ignore-src -r -y
colcon build --base-paths src --symlink-install
```

The dependency step also installs the core visualisation dependencies. A graphical
desktop is needed on the computer running RViz or a viewer; the driver can run
without a desktop.

## 2. Configure the host and board

From the repository root, create only missing local configuration files:

```bash
if [[ ! -e config/machine.env ]]; then
  cp config/machine.env.example config/machine.env
fi
if [[ ! -e config/boards.yaml ]]; then
  cp config/boards.yaml.example config/boards.yaml
fi
```

Both files are ignored by Git. Existing files are preserved. Edit
`config/machine.env` for the ROS installation on your host:

```bash
ROS_SETUP_FILE=/opt/ros/jazzy/setup.bash
ROS_DOMAIN_ID=0
AXIOM_ROS_BOARDS_FILE="$AXIOM_ROS_ROOT/config/boards.yaml"
```

The workspace defaults to this checkout. Set `ROS_WORKSPACE` only if you built in
a separate workspace. All ROS processes in this session must use the same domain
and compatible middleware settings. The setup script prepares a terminal; it starts
no nodes.

Choose either USB or Wi-Fi below, keeping one `axioms` mapping in `config/boards.yaml`.
The board key `axiom` selects the example namespace `/axiom`; it is not a hardware ID.

### USB

Find the stable Linux device path:

```bash
ls -l /dev/serial/by-id/
```

Configure the actual device path:

```yaml
axioms:
  axiom:
    transport: serial
    serial.port: /dev/serial/by-id/REPLACE_WITH_AXIOM_DEVICE
    auto_connect: false
    auto_reconnect: false
    autosub: false
```

If no by-id path is supplied, use the actual `/dev/ttyACM…` or `/dev/ttyUSB…` path.
Check its permissions and your account's groups:

```bash
ls -l /dev/ttyACM* /dev/ttyUSB* 2>/dev/null
id -nG
```

If the device belongs to `dialout` and your account is not a member:

```bash
sudo usermod -aG dialout "$USER"
```

Log out and back in before connecting. Use one application with the serial device
at a time; close an updater, serial monitor or USB router using this board first.

### Wi-Fi

Connect Axiom to your Wi-Fi network first. Replace the illustrative address
`192.0.2.10` with its reachable IP in both the board file and the check below:

```yaml
axioms:
  axiom:
    transport: ws
    device_uri: ws://192.0.2.10/ws
    auto_connect: false
    auto_reconnect: false
    autosub: false
```

```bash
curl --max-time 5 http://192.0.2.10/api/v
```

Expect a JSON reply with `rslt` equal to `ok` and a firmware version. This checks
reachability; the driver uses the framed `/ws` endpoint for control and data.

Sensors are discovered automatically. `boards.yaml` configures boards and optional
aliases, rather than a required list of sensors. The single-board launch loads the
[driver defaults](src/axiom_driver/config/axiom.yaml), then board settings, then
explicit launch arguments. The multi-board launch uses the same driver defaults
and each board's settings.

### Optional tmux consoles

After building and configuring the host, run from an outer terminal at the checkout:

```bash
sudo apt install tmux
bash scripts/ros_tmux.sh
```

The helper opens four empty panes labelled **Terminal 1–4**. New panes automatically
load `scripts/setup_env.sh`; start the driver and service calls yourself. Use the
labels rather than screen positions. Press Ctrl+b, release both keys, then an arrow
to switch panes, z to zoom, or d to detach. Rerun the helper to reattach.

See [tmux controls](docs/tmux.md) for copy/paste, scrolling and environment refresh.
In separate terminal windows, change to the checkout and source
`scripts/setup_env.sh` in each one. Do the same in reused panes after a rebuild.

## 3. Connect and inspect a measurement

In **Terminal 1**, from the repository root:

```bash
source scripts/setup_env.sh
ros2 launch axiom_driver axiom_minimal_launch.py \
  namespace:=axiom boards_file:="$AXIOM_ROS_BOARDS_FILE"
```

Leave it running. The configuration above starts disconnected with acquisition off.

In **Terminal 2**:

```bash
source scripts/setup_env.sh
ros2 service call /axiom/connect axiom_interfaces/srv/Connect '{device_uri: ""}'
ros2 service call /axiom/publish_data_subscription \
  axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 20.0}'
ros2 topic list -t --no-daemon
```

Both services should return `success: true`. The empty URI uses the board's configured
USB port or Wi-Fi endpoint. Connection alone does not enable acquisition. The 20 Hz
request controls firmware packet delivery, not each sensor's sampling rate.

For a connected supported IMU, find its full `sensor_msgs/msg/Imu` topic ending in
`/imu/data_raw`. Replace the placeholder below with that discovered path:

```bash
IMU_TOPIC='PASTE_DISCOVERED_IMU_TOPIC_HERE'
ros2 topic echo "$IMU_TOPIC" sensor_msgs/msg/Imu \
  --field linear_acceleration --qos-reliability best_effort --once
ros2 topic hz "$IMU_TOPIC"
```

The echo prints X/Y/Z acceleration in m/s², including gravity. The six-axis message
also contains angular velocity in rad/s, with no fused orientation. For another
sensor, choose its published topic and ROS type. On Jazzy, `topic hz` uses sensor-data
QoS by default. Its received message rate can differ from the requested delivery
rate because sensors sample independently and firmware can batch samples.

Stop the rate command with Ctrl+C. To inspect inventory:

```bash
ros2 topic echo /axiom/devices --qos-durability transient_local --once
```

An echo or viewer subscribes to ROS topics; it does not start firmware acquisition.
See [sensors and multiple boards](docs/sensors-and-boards.md) for aliases, commands
and reconnecting. After reconnecting an Axiom with manual settings, request
acquisition again.

## 4. Optional acceleration display in RViz

Keep the driver and acquisition running. In **Terminal 3**, build the optional
marker adapter from the repository root:

```bash
source scripts/setup_env.sh
rosdep install --from-paths src examples/scenarios-dashboard/src/axiom_marty_demo --ignore-src -r -y
colcon build --base-paths src examples/scenarios-dashboard/src/axiom_marty_demo \
  --packages-select axiom_marty_demo --symlink-install
source scripts/setup_env.sh
ros2 run axiom_marty_demo sensor_view --ros-args \
  -r __ns:=/sensing -p axiom_namespace:=/axiom
```

Leave it running. It discovers the IMU through `/axiom/devices` and publishes markers.
It requires neither the dashboard nor a Marty.

In **Terminal 4**:

```bash
source scripts/setup_env.sh
ros2 run rviz2 rviz2 \
  -d "$(ros2 pkg prefix --share axiom_marty_demo)/config/sensors.rviz"
```

The supplied layout uses the display frame `sensor_view` and topic
`/sensing/visualization/markers`. The acceleration arrow includes gravity; it is not
a position or orientation estimate. For an AMG8833, follow the separate
[RViz thermal guide](docs/thermal-camera.md) or
[single-camera Foxglove guide](examples/foxglove/README.md#thermal-camera-on-one-axiom).

## 5. Stop

Close viewers and stop echoes or adapters with Ctrl+C. While the driver is still
running, in Terminal 2:

```bash
ros2 service call /axiom/publish_data_subscription \
  axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 0.0}'
ros2 service call /axiom/disconnect axiom_interfaces/srv/Disconnect '{}'
```

Then stop the driver with Ctrl+C in Terminal 1. Detaching tmux or stopping an echo
alone leaves the running processes and acquisition active.

If a package or service is missing, check the successful build, sourced workspace,
driver process, namespace, ROS domain and middleware settings. For USB, also check
device permissions and port ownership. For Wi-Fi, check the current address and
`/api/v` response. Use the exact discovered topic and compatible best-effort QoS
when checking sensor messages.

Development and dated test evidence are in [validation.md](docs/validation.md).
The [firmware contract notes](docs/firmware-alignment.md) describe decoding, timing
and transport limits. Historical test versions are not installation requirements.
