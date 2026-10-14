# Optional Axiom scenarios dashboard

The browser guide explains commands, interfaces and the live ROS graph. Run its
commands in a console. The host driver, acquisition and visualisers work independently
of the dashboard. Axiom-only scenarios do not require a Marty.

Complete the [host-driver setup](../../README.md), including the local machine and
board files. Examples use Ubuntu 24.04/Jazzy; use the installed distribution's setup
file for another compatible installation. All consoles and the dashboard need the
same ROS domain and middleware settings.

## Build and open on Linux

If rebuilding while drivers/visualisers are active, stop their acquisition and
processes first, then restart them after the build. From the repository root:

```bash
source scripts/setup_env.sh
rosdep install --from-paths src examples/scenarios-dashboard/src --ignore-src -r -y
colcon build --base-paths src examples/scenarios-dashboard/src --symlink-install
source scripts/setup_env.sh
bash examples/scenarios-dashboard/scripts/dashboard.sh
```

The example's `COLCON_IGNORE` excludes it from default recursive discovery;
passing `examples/scenarios-dashboard/src` explicitly includes it. The optional
packages are `axiom_marty_dashboard` and `axiom_marty_demo`. The wrapper stays in
the foreground and starts the guide, with no drivers or acquisition.

Open **http://127.0.0.1:8083** on the ROS host, or the port in `machine.env`.
The server listens on loopback by default. For a viewer on another computer,
run an SSH tunnel there, replacing its login and the ROS host address:

```bash
ssh -N -L 8083:127.0.0.1:8083 USER@ROS_HOST_IP
```

Keep it running and open the same localhost URL on the viewer computer. If the
dashboard port differs, substitute that port in the tunnel and URL. Leave the
dashboard process running in a separate terminal while using ROS commands.

## Read the guide

| Tab | Purpose |
|---|---|
| Available | Catalogue of interfaces and relationships the packages can expose |
| Running graph | Discovered nodes/topics/services and publisher/subscriber edges |
| Commands | Console recipes grouped by purpose |
| Scenarios | Workflows from setup through cleanup; expand one step or all |

The board selector scopes recipes to a configured namespace. Information buttons
explain argument order, units, permitted values and interface fields. Discovery
shows registered endpoints, not whether commands succeeded or valid messages
arrived. Check service responses and sensor messages in the console. An echo can
keep a topic name registered after its publisher disappears; inspect publisher count.

Configured boards can appear before their drivers start. **Driver offline** means
no driver was discovered for that namespace. **Connected** reflects the driver's
reported connection state, not a separate cable or Wi-Fi test.

## Use four tmux consoles

From an outer terminal at the repository root:

```bash
sudo apt install tmux
bash scripts/ros_tmux.sh
```

New panes preload the environment; reused panes after a rebuild need
`source scripts/setup_env.sh`. Use Terminal 1 for the driver, Terminal 2 for
services/checks, Terminal 3 for the dashboard or visualiser, and Terminal 4 for
RViz or more checks. If the selected scenario needs both an adapter and RViz,
keep the dashboard in an extra outer terminal.

Ctrl+b then an arrow switches panes, z zooms, and d detaches. Rerun the helper
to reattach. See [tmux controls](../../docs/tmux.md) for copying output and scrolling.
The helper opens empty consoles; it starts no drivers.

## Axiom workflows

Use the configured USB port or framed `/ws` endpoint. Review copied commands for
example addresses and identities before running them. The ordinary single-board
recipes keep connection and acquisition manual:

1. Launch the selected driver and leave it running.
2. Call its connect service, then request acquisition.
3. Inspect inventory, topics and messages.
4. Run the optional adapter and viewer.
5. Stop viewers, stop acquisition, disconnect, then stop the driver.

The thermal scenario uses an AMG8833 8×8 camera. It selects a camera topic when
exactly one publisher is discovered; otherwise choose its identity-based topic.
Read the camera frame in the same terminal used for RViz. The camera's own frame
and the supplied 15–40 °C heatmap need no dashboard at runtime.

Walkthroughs: [sensor discovery/services and multiple boards](../../docs/sensors-and-boards.md),
[thermal RViz](../../docs/thermal-camera.md), and
[thermal Foxglove](../foxglove/README.md#thermal-camera-on-one-axiom).
Firmware must recognise a supported profile; aliases are optional names rather
than a list of installed sensors.

## USB + Wi-Fi scenario

This scenario generates a separate file with `axiom/front` and `axiom/rear`.
It uses **automatic connection and acquisition**, unlike the manual walkthroughs.
Stop any existing driver connected to either physical board first.

Before copying the configuration recipe, set the actual endpoints in the **same
terminal that will run that recipe**:

```bash
export AXIOM_ROS_TRANSPORT=serial
export AXIOM_ROS_SERIAL_PORT='/dev/serial/by-id/REPLACE_WITH_USB_AXIOM'
export AXIOM_WIFI_IP='REPLACE_WITH_WIFI_AXIOM_IP'
```

The recipe writes `~/usb_wifi_axioms.yaml`; review it before running the scenario's
multi-board launch. It does not reuse the two endpoints from your usual board file.
Both entries opt into `auto_connect: true`, `autosub: true` and 20 Hz packet delivery,
with `auto_reconnect: false`. The endpoints must belong to different physical Axioms.

After inspecting each IMU, the scenario frees Terminals 3 and 4 for the two-board
adapter and RViz. USB and Wi-Fi acceleration arrows have separate labels. Display
origins are a layout, not measured mounting transforms or pose estimates.
The ordinary [multi-board guide](../../docs/sensors-and-boards.md#multiple-boards)
uses manual per-board connect/acquisition calls instead.

## Optional Marty scenarios

These additionally require the `marty-ros2` repository and hardware. Place that
checkout beside `axiom-ros2`, then build from the Axiom repository root:

```bash
source scripts/setup_env.sh
rosdep install --from-paths src examples/scenarios-dashboard/src ../marty-ros2/src --ignore-src -r -y
colcon build --base-paths src examples/scenarios-dashboard/src ../marty-ros2/src --symlink-install
source scripts/setup_env.sh
```

Use the actual Marty connection settings in its recipes. Longer Marty motion
operations use its own action interfaces; Axiom descriptor commands use services.

## Finish

Stop viewers/echoes first. While each driver is running, call its stop-acquisition
and disconnect services, then stop the drivers and dashboard with Ctrl+C.
A **Start from scratch** control needs an optional workstation reset adapter;
it is not part of the normal Linux setup. The
[Mac adapter](platforms/macos/README.md) is a separate optional Docker/noVNC workflow.

Published walkthrough: [Scenarios dashboard](https://userguides.robotical.io/axiom/ros2/dashboard).
See [ROS concepts](docs/learn-ros2.md) and the dated
[validation record](docs/validation.md) for technical background and evidence.
