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

## 2. Start automatically

Connect a host-firmware Axiom over USB, or power a Wi-Fi Axiom on the same local
network. From the checkout:

```bash
source scripts/setup_env.sh
ros2 launch axiom_driver axiom.launch.py
```

No board file, serial path or IP address is required. With no boards, discovery
waits quietly. Verified boards connect and start acquisition automatically; each
gets a stable namespace `/axiom_<firmware-MAC>`. Multiple boards run independently,
and a board visible over USB and Wi-Fi gets one bridge, preferring USB.

For USB, ensure your account can access the port. On systems using `dialout`:

```bash
ls -l /dev/serial/by-id/
id -nG
# Only if your account is missing the device's group:
sudo usermod -aG dialout "$USER"
```

Log out and back in after changing groups. Close updaters, serial monitors and USB
routers using the same board. Wi-Fi discovery uses the firmware's mDNS HTTP
advertisement; the network must allow multicast. An explicit endpoint remains
available when multicast is blocked.

The optional `config/machine.env` selects a host's ROS setup, workspace and domain:

```bash
# Create only if you need host-specific settings; preserve an existing file.
if [[ ! -e config/machine.env ]]; then
  cp config/machine.env.example config/machine.env
fi
```

Edit `ROS_SETUP_FILE` for your installed distribution, for example
`/opt/ros/kilted/setup.bash` or `/opt/ros/jazzy/setup.bash`. All participating ROS
terminals must share a domain and compatible middleware settings. Sourcing the
setup script prepares a terminal without starting nodes.

See [automatic startup](docs/automatic-startup.md) for optional board names, aliases,
shared-network board selection, explicit endpoints and manual startup. Existing
board files can still name configured endpoints. New identity rules need no
endpoint. For example, a rule named `axiom` makes a selected board use `/axiom`
for the optional viewer examples below.

### Optional tmux consoles

```bash
sudo apt install tmux
bash scripts/ros_tmux.sh
```

The helper opens four prepared consoles without starting a driver. Run the launch
above in Terminal 1. New panes load the ROS environment automatically; after a
rebuild, source `scripts/setup_env.sh` in reused panes. See [tmux controls](docs/tmux.md).

## 3. Inspect a measurement

Leave discovery running. In a second prepared terminal:

```bash
source scripts/setup_env.sh
ros2 topic echo /axiom_discovery/boards --qos-durability transient_local --once
ros2 topic list -t --no-daemon
```

The board inventory reports each ID, namespace, transport and connection state.
Sensors are discovered automatically; they do not need entries in a board file.
For a supported IMU, copy its full `sensor_msgs/msg/Imu` topic ending in
`/imu/data_raw`:

```bash
IMU_TOPIC='PASTE_DISCOVERED_IMU_TOPIC_HERE'
ros2 topic echo "$IMU_TOPIC" sensor_msgs/msg/Imu \
  --field linear_acceleration --qos-reliability best_effort --once
ros2 topic hz "$IMU_TOPIC"
```

Acceleration is in m/s², including gravity; gyroscope values are in rad/s. The IMU
has no fused orientation. Packet delivery defaults to 10 Hz; a sensor's message
rate can differ because its sampling and firmware batching are independent.
Stop the rate command with Ctrl+C. Viewers subscribe to ROS topics and need no
additional connection or acquisition calls.

The remaining examples use a configured board name `/axiom`. Replace it with your
actual namespace, or add that optional name through the board file. See
[sensors and multiple boards](docs/sensors-and-boards.md) for services and aliases.

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
