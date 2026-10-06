# Firmware alignment validation

Validated on 2026-09-29 against the source baseline in
[firmware-alignment.md](firmware-alignment.md). The baseline does not identify a
physical board's flashed firmware.

## Reproduce

```bash
./scripts/validate_ros.sh
```

The script starts a disposable ROS Jazzy Ubuntu 24.04 container, installs declared
runtime/test tooling, mounts this repository read-only, builds all seven packages in
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

Latest clean run: **2026-10-06**, using `./scripts/validate_ros.sh`.
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

The clean build passed for all six packages. The final suite result is recorded in
`firmware-alignment-plan.md`. Four pre-existing copyright-template tests remain
skipped; no functional test is skipped in the ROS container. The ament flake8 runner
emits Python warnings about forking from a multithreaded process; lint passes.

The container checks above use source-derived fixtures and virtual peers. The GUI
visualizers were linted/built and their history logic tested; no graphical desktop
rendering was tested in Docker. A subsequent physical USB check is recorded below.

## Physical USB check — 2026-09-29

The repository's `core.Session` and `core.Pipeline` connected on macOS through
`/dev/cu.usbmodem2101`, at 115200 baud with serial mode `auto` (OverAscii-framed
RICREST). The board identified itself as **Axiom018**, firmware **0.1.16-devlib**.
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
native ROS is not installed on this Mac. No firmware was changed/flashed, sample
rates configured, or actuator commands sent.

## Movement lab: full ROS and physical USB — 2026-09-29

The later [shake detector project](shake-lab.md) extended the earlier USB check to
the actual ROS node and DDS subscribers. ROS Jazzy runs in Docker on this Mac, with
a loopback-only host USB/OverAscii-to-RICSerial relay. The ROS driver owns the
subscription; the relay does not acquire or decode measurements independently.

- All **seven packages built**. The aggregate colcon result was **91 tests, zero
  errors, zero failures, four existing copyright skips**. The new package contributed
  22 passing tests, including real DDS and HTTP integration plus lint.
- The real Axiom018 streamed `sensor_msgs/Imu` through the driver into the shake
  detector and browser dashboard. Before deliberate movement, over 5,000 readings
  arrived without a shake event.
- The user physically shook the board. The detector emitted **event #1**, with
  three pulses and motion magnitude **3.22 m/s²** at the triggering sample. This
  validates one real gesture, not general gesture-recognition accuracy.
- A real-device resting recording retained **2,060 IMU messages**. Playing only its
  IMU topic into a fresh detector delivered all 2,060 messages and produced zero
  shake events. The recording began after the user's gesture; it is not a recording
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
