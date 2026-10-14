# Axiom + ROS 2: a five-minute teaching demo

**One sensor, several independent applications.** The platform is designed to show
what ROS contributes: typed messages, independent subscribers, recording and replay.
It runs locally, with either a real USB-connected Axiom or a labelled synthetic clip.

## Open the teaching platform

This optional teaching platform owns its ROS applications and, in live mode,
automatically connects and requests acquisition. That differs from the manual
host-driver walkthroughs in the [README](../README.md). Use host firmware and
one acquisition owner per board; stop any other driver connected to that Axiom.

On macOS, from the repository root with Docker Desktop running:

```bash
./scripts/shake_lab.sh setup  # first use only
./scripts/shake_lab.sh start # live Axiom; selects a single matching USB device
```

Open **http://localhost:8080** on the host computer. For an explicit USB port,
replace the placeholder below with the actual macOS serial device:

```bash
./scripts/shake_lab.sh start /dev/cu.usbmodemREPLACE_WITH_AXIOM_DEVICE
```

Without hardware:

```bash
./scripts/shake_lab.sh start-demo
```

Then use **Play synthetic sample** in the browser. It supplies two programmed
movement gestures, clearly labelled as synthetic; it does not pretend to be live
hardware. To switch an offline-only Mac launch to USB, stop and start in live mode
so the host USB relay is available.

The walkthrough, robot face, recording and replay controls are all in the browser.
Use **Presentation view** for a larger stage, or the numbered sidebar for a guided
lesson. Presenter notes include a short explanation to say aloud and the actual
node names discovered through ROS.

## Present the demo

| Step | Do this | Say this | ROS concept |
|---|---|---|---|
| 1. See the measurements | Keep Axiom still, then tilt it. Point to acceleration and optionally expand rotation. | “The driver turns physical movement into messages that other applications can use.” | Standard messages and topics |
| 2. Recognise a shake | Move the board back and forth several times. Show the count and latest typed event. | “This node recognises a pattern. ROS delivers the measurements; our Python algorithm decides whether they form a shake.” | A node with one responsibility |
| 3. Add an application | Click **Add robot face**, then shake again. Stop it and show that measurements and detection continue. | “We added an application without changing the driver or detector.” | Independent subscribers |
| 4. Record an experiment | Record 15 seconds: still, shake, still, shake. Wait for the saved-message count. | “The recorder is another listener on the same topic.” | Multiple consumers and rosbag2 |
| 5. Unplug & replay | After recording finishes, unplug Axiom, select that recording, and replay it. | “The input now comes from a recording. The applications use the same interfaces.” | Replaceable publishers and repeatable experiments |

For the final step, **Replay selected** stops the live driver before starting the
bag player. The detector and face start a fresh experiment, so their counters reset.
Only IMU input is replayed; saved shake events are excluded and detections are
computed again. Changing playback speed uses the original source timestamps for
the detector, rather than changing the gesture rules.

**Play synthetic sample** is an alternative for a classroom without hardware. Add
the face first to show its reactions. Ask the audience to predict the result before
playing. With the default detector, the six-second sample produces two shake events.

For a technical extension, click **Add strict detector**, then replay the same clip
from its beginning. Both detectors receive the same IMU messages. The standard
threshold is 3 m/s² and the strict threshold is 8 m/s²; the supplied sample gives
**two standard events and zero strict events**. These are deliberately different
heuristics, not measures of algorithm accuracy.

## What actually runs

```text
Live Axiom → USB relay → axiom_bridge_node ─┐
                                          ├→ IMU topic ─┬→ teaching_dashboard
Recorded/synthetic clip → rosbag2 player ──┘             ├→ shake_detector
                     (one active input)                 ├→ rosbag2 recorder (optional)
                                                        └→ strict_detector (optional)

shake_detector → ShakeEvent topic ─┬→ robot_face → face/state → teaching_dashboard
                                  └→ teaching_dashboard
```

The teaching platform starts and stops independent OS processes using ROS CLI
commands. The face is its own `robot_face` ROS node and imports neither the hardware
driver nor the detection algorithm. It subscribes to real `ShakeEvent` messages and
publishes its expression and reaction count on `/axiom/face/state`. Browser controls
do not fabricate shakes or increment the face locally.

The dashboard is also a separate ROS node. Its graphs subscribe to IMU and motion
messages, so stopping the face does not interrupt them. It displays actual node and
subscription discovery, alongside a simplified diagram of the architecture.

The face counts events **since it was added**. It does not receive old shake events.
Stopping and adding it again resets its own count without resetting the detector.
Source changes restart the consumers together to give replay a fresh, comparable
experiment. The optional strict detector also counts from its own startup.

| Topic | Type | Purpose |
|---|---|---|
| Selected IMU topic | `sensor_msgs/msg/Imu` | Acceleration in m/s² and rotation in rad/s |
| `/axiom/shake/events` | `axiom_interfaces/msg/ShakeEvent` | Source timestamp, event number, triggering motion and pulse count |
| `/axiom/shake/motion` | `std_msgs/msg/Float64` | Motion magnitude after estimating slow gravity changes |
| `/axiom/shake/count` | `std_msgs/msg/UInt64` | Current detector event count |
| `/axiom/face/state` | `std_msgs/msg/String` containing JSON | Expression, reactions and last received event number |
| `/axiom/strict/events`, `/axiom/strict/count` | Same event/count types | Independent high-threshold detector outputs |

## Recording and playback controls

The browser records for 10, 15 or 30 seconds, with a countdown and an early-finish
button. A clip is offered for replay only when it contains IMU messages. Recording
requires live input. Source switches are blocked while a recording is active.
Discovery takes a short time, so a clip can contain slightly less data than the
selected recording duration.

Clips are saved in `.shake-lab/recordings/`, excluded from Git. Their original
message timestamps are retained. The graphs show the last ten seconds of arriving
messages; they are a presentation view, not a synchronized measurement analysis.
The simple motion graph follows the separate motion topic and is not an exact
per-sample join with the raw IMU messages.

The same teaching controls are available from the terminal:

```bash
./scripts/shake_lab.sh record 15
./scripts/shake_lab.sh replay movement-YYYYMMDD-HHMMSS-MICROSECONDS
./scripts/shake_lab.sh demo  # creates and plays a synthetic clip
./scripts/shake_lab.sh live  # return to hardware if launched with the USB relay
./scripts/shake_lab.sh status
./scripts/shake_lab.sh logs
./scripts/shake_lab.sh stop
```

Recording duration from the CLI is 5–120 seconds. Source changes do not restart the
web server. After editing source, stop and start the lab to rebuild and load changes.
The runtime, recordings, virtual environment and cached ROS builds live under
`.shake-lab/`. Per-node process logs are in `.shake-lab/recordings/.<node>.log`.
No service is installed to start automatically at login or boot.

## What the algorithm does

A low-pass filter estimates the slowly changing gravity vector. The detector
subtracts that estimate and measures the remaining acceleration magnitude. A pulse
starts above 3 m/s² and must fall below 1.2 m/s² before another pulse can start.
Three pulses within 0.8 seconds trigger an event, followed by a 1.5-second cooldown.
The filter settles for 0.5 seconds after startup or a timestamp discontinuity.

This is an educational heuristic. Fast rotations, repeated impacts and cable
movement can also trigger it. ROS does not supply the gesture-recognition rules.
Driver timestamps are estimates, and corrections can restart filter warmup.

## Run on native Linux ROS

Follow the [host setup](../README.md) to build the core packages and identify
the board's actual IMU topic. If using the manual driver to discover that topic,
stop acquisition, disconnect and stop it before launching this managed teaching
platform. From the repository root, substitute the actual USB port and IMU topic:

```bash
source scripts/setup_env.sh
IMU_TOPIC='PASTE_DISCOVERED_IMU_TOPIC_HERE'
ros2 launch axiom_shake_detector shake_lab.launch.py \
  transport:=serial serial_port:=/dev/serial/by-id/REPLACE_WITH_AXIOM_DEVICE \
  imu_topic:="$IMU_TOPIC"
```

The platform starts its own driver with automatic connection/acquisition. For a
Wi-Fi board, use `transport:=ws` and `device_uri:=ws://AXIOM_IP/ws`, replacing
`AXIOM_IP` with its actual address. Its direct managed driver uses these launch
arguments rather than reading the manual driver's board entry. All ROS applications
must use matching domain/middleware settings. Open the browser on the host, or
use an SSH tunnel if viewing its default loopback server from another computer.

Launch parameters include `imu_topic`, `dashboard_host`, `dashboard_port`,
`recordings_dir`, `with_driver`, `transport`, `device_uri` and `serial_port`.
The standalone `shake_detector` executable remains available for direct ROS use
and supports the original threshold/filter parameters and simple diagnostic page.
The teaching platform uses its fixed standard and strict configurations.

Select the IMU topic discovered from your board rather than assuming the
platform's built-in example identity. On macOS, set `AXIOM_IMU_TOPIC` before
starting the lab; on native Linux use the `imu_topic` launch argument. The optional
`with_driver:=false` mode starts without a managed live source for replay; stop
external live publishers before replaying on that same topic.

The Mac uses a loopback USB-to-WebSocket relay because the Linux container cannot
open the Mac serial path directly. Only the driver owns firmware acquisition.
Docker publishes the browser port only on loopback; the teaching control API accepts
same-origin JSON actions from this local page. This is a local demonstration,
not a multi-user or internet deployment.

## Validation

See [validation.md](validation.md). Automated tests exercise the detector, real DDS
message delivery, independent face and strict-detector processes, synthetic MCAP
playback at two speeds, preservation of the detector when the face stops, recording
path validation and rejection of cross-origin control requests. Browser checks and
real USB capture supplement those tests.
