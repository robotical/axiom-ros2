# Firmware alignment validation

This is dated development evidence, not a setup guide. Use the [README](../README.md)
and [published user guides](https://userguides.robotical.io/axiom/ros2/start) for
current installation and firmware selection. Historical firmware versions, test
environments and sensor identities below describe those checks, not requirements
for a user's host or boards. Results apply to their recorded source snapshots.

## Servo joint sliders — 2026-10-19

The [servo demo](servo-slider.md) adds `axiom_servo_demo`: the unchanged
`joint_state_publisher_gui` used by Marty, an adapter to existing descriptor angle
and enable services, and a labelled RViz target preview. The adapter selects one
live device, starts disarmed, converts radians to the selected command units and
keeps only the latest pending target. Reported joint position stays separate.

Validation used a disposable ROS Jazzy container from the local
`marty-ros2:jazzy` image. Source was mounted read-only, and the interfaces, driver
and demo were built into an empty workspace. All **14 package tests passed**:
five pure selection/encoding/gating checks, six real DDS service-adapter
scenarios, the installed-launch/real-GUI test and both ROS style checks. The GUI
ran with Qt's offscreen platform; the test confirmed the actual slider output,
configured URDF limits, preview TF and absence of a second acquisition driver.

Service scenarios cover no automatic startup/enable angle, explicit disable,
coalescing delayed requests, firmware rejection, replacement during enable,
disable superseding enable, inventory/slider expiry, RPC timeout and separate
reported feedback. The launch argument listing, shell syntax and diff whitespace
checks also pass. Linter workers emit existing Python fork/thread warnings.

Reproduce after building and sourcing the workspace:

```bash
colcon test --base-paths src --packages-select axiom_servo_demo \
  --event-handlers console_direct+ --return-code-on-test-failure
colcon test-result --verbose
ros2 launch axiom_servo_demo servo_demo.launch.py --show-args
```

The repository validation script now installs the slider/robot-state/RViz runtime
dependencies and inspects the new launch arguments. The full repository suite
was not rerun for this addition. Tests use synthetic inventory and command-service
peers. Physical servo movement, the new board's live descriptor and onscreen
RViz rendering were not exercised.

## Foxglove sound layout — 2026-10-16

The [sound demo](../examples/foxglove/sound-demo.md) adds a single-import layout
with six scalar time plots, a latest-message nine-band spectrum and a guide panel.
All 15 scalar attributes use the existing Float64 outputs. Its embedded user
script reads the timestamped DeviceSample JSON through a sensor alias; no ROS
driver, interface or firmware changes are needed for this layout.

Validation completed with Node.js 24.14.0: **eight focused tests passed**, covering
the actual descriptor's scalar coverage and frequency labels, embedded-source
consistency, panel references, engineering/negative values, invalid bins,
malformed input and recovery. Run them from the repository root:

```bash
node --test examples/foxglove/test_sound_demo.mjs
```

All seven Plot settings, the Markdown settings and UserScript payload round-trip
exactly through the official Foxglove SDK 0.29.2 configuration classes, with
configured enum values checked. TypeScript 7.0.2 passes strict no-emit checking
against a representative generated ROS input/Header schema. The documented
16-alias YAML fragment validates through the real driver alias helpers, binds
to one sensor and remains unbound for ambiguous matches. Local documentation
links resolve, all seven shell blocks pass `bash -n`, and `git diff --check`
passes.

These are source/configuration checks with synthetic samples. Live Foxglove
script compilation/layout import/rendering, DDS delivery from a physical sound
sensor and Pi/Kilted acceptance were not exercised in this run.

## Host grid images — 2026-10-14

The host driver now adds `thermal/image` and `range/image` as standard
`sensor_msgs/msg/Image` messages with `32FC1` encoding. Thermal data retains
Celsius units and the existing `ThermalGrid` output. Descriptor-defined multizone
distance arrays use metres, valid status codes and the active 4×4/8×8 dimensions;
unused padding and invalid zones do not become false distance measurements.
Existing scalar range, IMU and generic sample behavior is retained.

Validation completed on macOS with Python 3.13 and a disposable Linux ROS Jazzy
container using the locally built `axiom-shake-lab:jazzy` image. Source was mounted
read-only; all seven packages were built into an empty container workspace.
The complete colcon suite reported **119 tests, zero errors, zero failures and
four existing copyright-check skips** (115 passed). A separate pure-client run
passed **65 tests**. Firmware and Raft repository HEADs, diffs and working-tree
states were compared before and after this task and remained unchanged.

New regressions cover released AMG8833/VL53L5CX descriptors, signed thermal
pixels, float32 byte order and row stride, distance conversion, accepted/rejected
zone statuses, nonfinite values, 4×4 padding and malformed dimensions. Two
independent WebSocket firmware peers and real ROS subscribers verify all four
image aliases, board/frame isolation, preserved generic and thermal messages,
per-topic QoS, removal/reappearance and recovery to an 8×8 image after a rejected
frame. These tests use synthetic sensor payloads rather than physical sensors.

The [thermal layout](../examples/foxglove/one-axiom-thermal.json) has one Image
panel for `/axiom1/thermal/image`, validated against the official Foxglove SDK
0.29.2 configuration model. It replaces the initial four-panel heatmap layout.
Its panel identifiers and aliases were also checked. The saved image settings
round-trip through the SDK without changes. Import instructions and colour-scale
settings are in the [Foxglove guide](../examples/foxglove/README.md#thermal-camera-on-one-axiom).

Physical VL53L5CX operation, mounting orientation and GUI rendering/import on
other workstations were outside this automated run. The container result validates
ROS Jazzy; it is not a build result for other distributions.

Validated on 2026-09-29 against the source baseline in
[firmware-alignment.md](firmware-alignment.md). The baseline does not identify a
physical board's flashed firmware.

## Reproduce

```bash
./scripts/validate_ros.sh
```

The script starts a disposable ROS Jazzy Ubuntu 24.04 container, installs declared
runtime/test tooling, mounts this repository read-only, builds all packages in
an empty workspace, runs the entire colcon suite and inspects installed launch
arguments. The base image digest is pinned in the script; apt packages are resolved
at execution time. `ROS_VALIDATION_IMAGE` can explicitly select another image.
The GitHub workflow runs the same script; its remote run has not been observed here.

For pure client tests on a machine without ROS:

```bash
python3 -m venv /tmp/axiom-client-tests
/tmp/axiom-client-tests/bin/pip install pytest pyserial websocket-client websockets
PYTHONDONTWRITEBYTECODE=1 /tmp/axiom-client-tests/bin/python -m pytest -q -p no:cacheprovider \
  src/axiom_driver/test/test_firmware_contract.py \
  src/axiom_driver/test/test_pipeline.py \
  src/axiom_driver/test/test_session.py \
  src/axiom_driver/test/test_serial_integration.py
```

## Evidence and coverage

Earlier clean run: **2026-10-06**, using `./scripts/validate_ros.sh`.
All seven packages built. Colcon reported **99 tests, zero errors, zero failures,
four existing copyright-check skips** (95 passed). The driver contributed 59
passing tests, including descriptor commands, aliases, hot-plug lifecycle and
the installed multi-board launch. Installed bringup arguments were also checked.
This run used firmware peers and virtual serial ports; it did not access hardware.

| Requirement | Evidence |
|---|---|
| Current metadata/envelope | Version/type/address/status fixtures, legacy support, first-packet metadata buffering |
| Decoding | All 39 ordinary catalogue layouts fit; synthetic vectors for all six custom handlers; scaling, signs, arrays, invalid range, SI mass/acceleration distinction |
| Timing | Wrap, long gap, reboot-like backward counter, ROS clock change, buffered receipts, FIFO ordering and overlap |
| Lifetime | Registry capacity and bounded pending records; stale metadata tokens; removal, retry, reset and installed-profile refresh |
| Transport | Real local WebSocket server; POSIX pseudo-terminal tests for auto/OverAscii/ASCII; CRC fragmentation, failed serial open, concurrent RPCs, cancellation, disconnected readiness |
| ROS messages | Real generated interfaces and DDS; SI IMU/covariance/stamps; invalid range retains raw value; two simultaneous subscribers receive identical generic data |
| Services | Real sample-rate service checks firmware confirmation; disconnect/state; three automatic reconnect/resubscription cycles with the first new-session packet retained |
| QoS/configuration | Per-topic reliable publisher and local history depth; read-only startup parameters; installed launch with JSON overrides and clean SIGINT shutdown |
| Tooling | Bringup exposes every driver option; timestamp-based plot history expiry/reset/capacity; package lint and XML checks |

The original alignment milestone built six packages; its result is recorded in
`firmware-alignment-plan.md`. Later runs above include seven packages. Four pre-existing copyright-template tests remain
skipped; no functional test is skipped in the ROS container. The ament flake8 runner
emits Python warnings about forking from a multithreaded process; lint passes.

The container checks above use source-derived fixtures and virtual peers. The GUI
visualizers were linted/built and their history logic tested; no graphical desktop
rendering was tested in Docker. A subsequent physical USB check is recorded below.

## Physical USB check — 2026-09-29

The repository's `core.Session` and `core.Pipeline` connected to a test Axiom
through its macOS USB serial device at 115200 baud, using serial mode `auto`
(OverAscii-framed RICREST). That board reported firmware **0.1.16-devlib**.
Its version response does not establish the exact flashed Raft module commits.

Initial captures exposed two client defects, now covered by regression tests:

- Firmware-owned bus-zero devices need `devman/typeinfo?deviceid=0_1`; the physical
  bus lookup returned `failBusNotFound` for the Power device.
- Console status JSON, including `NetMan.wifiSTA`, must stay on the console path
  instead of being parsed as device publications. Current and legacy device
  envelopes remain accepted, including unsupported versions for explicit errors.

After those fixes, a 12.00-second capture received 78 devjson publications and
decoded 1,376 readings: 1,286 LSM6DS IMU, 12 MAX17048 fuel-gauge and 78 Power status
readings. All three devices were online with metadata ready. Five version requests
averaged **22.38 ms** round-trip (20.16–23.74 ms). There were no transport/decoder
errors, reported device overflows or dropped pending records. Battery voltage was
about 4.20 V; IMU acceleration was approximately `(0.13, 0.04, -9.70)` m/s². These
are connectivity observations, not calibration measurements or a throughput test.

The connection stayed ready throughout capture. Subscription and unsubscription
were acknowledged, and the serial port was closed at the end. Repeated connections
also completed the firmware handshake. All **46 pure-client tests** passed after
the fixes; the earlier full ROS container result predates these two changes.
The sanitized Power metadata/payload regression is in
`src/axiom_driver/test/fixtures/axiom_power_usb.json`.

Timing remains a separate limitation: 68 records were marked with uncertain
timestamps, and the final Power record had `uncertain_overlap`. The inspected
firmware's `DevicePower::formDeviceDataResponse` serializes its last status-update
time in milliseconds, whereas the client currently defaults to 100-microsecond
bus-poll ticks. Repeated status snapshots can also repeat timestamps. Power sample
timestamps therefore need a distinct clock contract before precise timing claims.

This check exercised the real serial transport, RPC, discovery and decoding paths.
It did **not** launch the ROS node or verify DDS topics from this physical board:
native ROS was not installed on that host. No firmware was changed/flashed, sample
rates configured, or actuator commands sent.

## Movement lab: full ROS and physical USB — 2026-09-29

The later [shake detector project](shake-lab.md) extended the earlier USB check to
the actual ROS node and DDS subscribers. That check ran ROS Jazzy in Docker on macOS, with
a loopback-only host USB/OverAscii-to-RICSerial relay. The ROS driver owns the
subscription; the relay does not acquire or decode measurements independently.

- All **seven packages built**. The aggregate colcon result was **91 tests, zero
  errors, zero failures, four existing copyright skips**. The new package contributed
  22 passing tests, including real DDS and HTTP integration plus lint.
- The physical test Axiom streamed `sensor_msgs/Imu` through the driver into the shake
  detector and browser dashboard. Before deliberate movement, over 5,000 readings
  arrived without a shake event.
- A physical shake was performed on the test board. The detector emitted **event #1**, with
  three pulses and motion magnitude **3.22 m/s²** at the triggering sample. This
  validates one real gesture, not general gesture-recognition accuracy.
- A real-device resting recording retained **2,060 IMU messages**. Playing only its
  IMU topic into a fresh detector delivered all 2,060 messages and produced zero
  shake events. The recording began after that gesture; it is not a recording
  of that gesture.
- After increasing the FIFO burst buffers, a further real-device recording retained
  **1,033 IMU messages and 1,033 derived motion messages** over 9.60 seconds. The
  recorder now checks both live input readiness and a nonzero saved IMU count.
- A separately labelled synthetic six-second MCAP contained **600 IMU messages**
  and two programmed gestures. Replaying at both **1× and 2×** produced exactly
  two events at identical source timestamps, **101.27 s and 104.27 s**. Recorded
  detector output topics are excluded from replay so events are recomputed.
- Visual inspection confirmed the live acceleration and motion plots, topic name,
  receiving status, sample count and real shake event in the browser.

Runtime logs, evidence snapshots, cached builds and recordings are kept under the
Git-ignored `.shake-lab/` directory. The lab uses 256-sample best-effort queues for
driver publication, detector subscription and bag recording to absorb FIFO bursts;
best-effort delivery still does not promise zero loss under arbitrary load. After
playback validation the live USB lab was restored. It can be stopped with
`./scripts/shake_lab.sh stop`.

The host relay is launched in its own process session so it stays alive when the
invoking shell exits; this was verified after the launcher completed. Startup waits
for actual IMU data in live mode, rather than only HTTP readiness.

The earlier Power clock limitation remains. The movement detector consumes only
IMU data, resets its filter after source-time discontinuities, and is a configurable
educational heuristic. Broader physical calibration, reconnect/unplug testing and
sensor coverage below remain outstanding.

## Guided ROS teaching demo — 2026-09-29

The movement lab now has a five-step lesson, live ROS graph, independent robot-face
subscriber, presentation view, and browser controls for recording and replay.

- All **seven packages built**. The full colcon result was **92 tests, zero errors,
  zero failures, four existing skips**. The teaching integration test uses real ROS
  processes and DDS, including the dashboard, standard detector, strict detector
  and robot face.
- The synthetic six-second clip delivered **600 IMU messages**, **two standard
  shake events**, **two face reactions** and **zero strict-detector events**.
  Replay at 1× and 2× preserved event source timestamps of **101.27 s and 104.27 s**.
- Stopping the face left the detector process running with the same PID. Discovery
  reported three IMU subscribers and two shake-event subscribers while both optional
  consumers were running, demonstrating independent topic subscriptions.
- Recording through the browser saved **1,006 real USB IMU messages** over **9.38
  seconds**, with automatic finalization after the requested ten-second window.
  This recording used the resting board; no new physical shake was requested.
- Integration checks rejected recording without live input, recording-path
  traversal and cross-origin control requests.
- Browser inspection verified the lesson, actual ROS-driven face expression,
  synthetic/live source labels, recording controls, comparison counts and
  presentation view. Replay consumes only recorded IMU input; shake events and face
  reactions are calculated again by their respective ROS nodes.

Evidence and recordings remain in the Git-ignored `.shake-lab/` directory. These
checks validate the teaching workflow, not broader physical gesture accuracy.

## Hardware acceptance still needed

1. Record the board's `v` response and compare its actual module revisions, especially
   RaftSysMods, with the inspected baseline.
2. Connect representative ordinary, FIFO and thermal sensors; compare known physical
   inputs with ROS units/signs, validity and frames.
3. Set a supported sample rate and vary delivery rate; record DeviceSample, metadata,
   raw/devjson and diagnostics for sustained-run loss/latency assessment.
4. Unplug/replug sensors, interrupt USB/Wi-Fi, reboot the board and confirm discovery,
   reconnection and uncertainty indicators with that firmware build.
5. Run multiple ROS consumers through the same bridge. Keep other firmware acquisition
   clients closed because the upstream queue currently has destructive reads.

These broader acceptance steps remain outstanding beyond the specific physical
USB and movement-lab checks above. No firmware files were changed or flashed.
