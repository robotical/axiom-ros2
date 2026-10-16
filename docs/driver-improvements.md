# Host driver development plan

Status: automatic USB/Wi-Fi startup implemented and validated; breaking readable
topic migration committed and published as `7e5bec9`; Illuminance and scalar
fallbacks implemented and validated. Optional descriptor ROS
mapping metadata remains a later increment.
Prepared: 2026-10-16.
Working branch: `main`, as requested.

This is a working development record for improving startup, discovery, topic
naming and measurement messages. The [README](../README.md) and
[driver reference](../src/axiom_driver/README.md) describe current behaviour.
Sections marked as proposals are not implemented features or installation
instructions. Completed increments and their validation are recorded below.

## How we will work

- Nikos writes the implementation. The assistant helps explain the code, define
  each increment, review diffs, and write and run tests. Implementation changes
  by the assistant are discussed first.
- Work on one small increment at a time on `main`. No firmware or Raft library
  changes are included in this plan.
- Before coding, agree on observable behaviour, compatibility and acceptance
  checks. Keep unresolved choices visible instead of implementing assumptions.
- Review each focused diff, address valid findings, run the relevant checks, then
  make a focused commit. Do not include unrelated pending edits in that commit.
- Record decisions and verification below. A short entry per completed increment
  is sufficient; there is no requirement to record every command.
- Keep automated checks separate from physical hardware acceptance. Record the
  ROS distribution and tested source revision with each result.
- Commit and push only when explicitly requested.

## Baseline and existing local work

On 2026-10-16, `main` and freshly fetched `origin/main` both point to
`51c6e488159a99cb8baae509357312f21400fd5d`
(`Align ROS documentation with generic user guides`). Neither is ahead or behind.

Before this document was created, there were 29 modified tracked files, no staged
changes and no untracked files. They contain 205 insertions and 49 deletions.
All were preserved. This is a documented working-tree baseline, not a clean
committed baseline. The new development plan is a separate documentation change.

| Existing work | Files | What changed |
|---|---:|---|
| Mac demo adapter, documentation and supporting tests | 11 | Read the shared machine/board configuration; use configured workspace, ROS domain and dashboard port in the desktop, launch and reset paths; retain CLI-generated board configuration as a fallback; adjust WebSocket and ROS CLI compatibility tests. |
| Formatting in ROS packages | 17 | One blank line added after a class declaration in each file; no behaviour changes. This includes the pending driver/session/serial edits. |
| Quick-reference document | 1 | `usefull.md` has lost its final newline; its visible text is unchanged. |

The 11 demo-related paths are:

```text
examples/scenarios-dashboard/platforms/macos/README.md
examples/scenarios-dashboard/platforms/macos/container_demo.py
examples/scenarios-dashboard/platforms/macos/demo.py
examples/scenarios-dashboard/platforms/macos/desktop/app.sh
examples/scenarios-dashboard/platforms/macos/desktop/bashrc
examples/scenarios-dashboard/platforms/macos/session_reset.py
examples/scenarios-dashboard/platforms/macos/test_host_runtime.py
examples/scenarios-dashboard/platforms/macos/test_session_reset.py
examples/scenarios-dashboard/platforms/macos/test_usb_ws_relay.py
examples/scenarios-dashboard/scripts/build_workspace.sh
examples/scenarios-dashboard/src/axiom_marty_dashboard/test/test_commands.py
```

The 17 formatting-only paths are:

```text
src/axiom_debug_tools/axiom_debug_tools/env_monitor.py
src/axiom_debug_tools/axiom_debug_tools/imu_monitor.py
src/axiom_debug_tools/axiom_debug_tools/range_monitor.py
src/axiom_debug_tools/axiom_debug_tools/topic_sniff.py
src/axiom_driver/axiom_driver/axiom_bridge_node.py
src/axiom_driver/axiom_driver/core/rpc.py
src/axiom_driver/axiom_driver/core/session.py
src/axiom_driver/axiom_driver/descriptor_services.py
src/axiom_driver/axiom_driver/mini_hdlc.py
src/axiom_driver/axiom_driver/protocols/ric_serial.py
src/axiom_driver/axiom_driver/publisher_cache.py
src/axiom_driver/axiom_driver/transports/serial.py
src/axiom_driver/test/test_serial_integration.py
src/axiom_plotter/axiom_plotter/dynamic_grapher.py
src/axiom_plotter/axiom_plotter/history.py
src/axiom_shake_detector/axiom_shake_detector/node.py
src/axiom_shake_detector/axiom_shake_detector/presentation.py
```

The user subsequently reviewed this inventory and explicitly authorised committing
and pushing all existing work and this plan to `main`. The existing work is now
separated into these commits:

- `40eb894`: share machine configuration across the Mac demo runtime (11 files).
- `87c30af`: save existing formatting-only edits (18 files, including `usefull.md`).

This plan is committed separately to complete the baseline. Future feature commits
should contain only their own implementation, tests and documentation. The earlier
dirty-tree inventory above is retained as historical evidence.

Ignored `config/machine.env` and `config/boards.yaml`, if present, are local runtime
configuration rather than part of the tracked development baseline. Leave them
alone during this preparation.

## Goals and scope

1. Make decoded measurements directly usable through appropriate standard ROS
   messages and a documented scalar fallback.
2. Make normal startup connect, acquire and recover automatically, with manual
   operation still available.
3. Discover USB Axioms and manage one driver session per physical board.
4. Provide readable, consistent topic names while retaining collision-free
   identity and a migration route for existing consumers.
5. Allow optional descriptor metadata to select supported ROS mappings.
6. Add Wi-Fi discovery with explicit robot membership and transport deduplication.

Preserve decoded engineering values, validity, sample timing, frames, QoS,
hot-plug lifetime and multi-board isolation. Keep one firmware acquisition owner
per physical Axiom. Additional visualisers consume ROS topics.

## Milestones

Each milestone needs a brief contract review before its implementation begins.
The user selected startup and USB discovery as the first priority. The milestone
numbers below are reference labels, not implementation order.

| Milestone | Intended result | Completion evidence |
|---|---|---|
| M0: baseline | Existing edits understood; current test results recorded; existing work kept separate. | Baseline inventory, test evidence and an explicit decision about pre-existing edits. |
| M1: measurement output | LTR-390 light and UV values are accessible as numeric ROS fields; supported scalar attributes have a generic fallback. | Decoder fixtures, real ROS message delivery and removal/reappearance checks, plus a hardware check when available. |
| M2: startup defaults | Normal startup connects and acquires; unexpected loss retries; intentional stop/disconnect remains effective. | Startup, absent-board, reconnect, explicit-stop and shutdown tests with firmware peers. Update parameter files, launch behaviour and docs together. |
| M3: USB discovery | Connected Axioms are verified and assigned stable board identities; hot-plug manages independent sessions. | Zero/one/multiple boards, non-Axiom candidates, busy ports, unplug/replug, changed device paths and duplicate-owner checks. Physical USB acceptance separately. |
| M4: naming | Topics identify sensor type and measurement, with stable uniqueness and an agreed compatibility policy. | Same-address devices on different buses, repeated sensor types, name sanitisation, replacement, aliases, services, frames and updated layouts/tools. |
| M5: descriptor mappings | A versioned optional metadata block selects supported message types and fields; descriptors without it still work. | Validation, precedence, unsupported mappings, missing fields, malformed metadata and fallback checks. Verify metadata survives the library upload/readback path before publishing profiles. |
| M6: Wi-Fi discovery | Discovery finds verified boards and honours robot membership; a board visible over USB and Wi-Fi gets one owner. | Discovery timeout/reappearance, unrelated devices, selection rules, stable namespaces and cross-transport deduplication. Physical network acceptance separately. |

## First increment: USB startup with no boards

The first increment added the standalone `axiom_usb_discovery` executable, which starts
[UsbDiscoveryNode](../src/axiom_driver/axiom_driver/usb_discovery_node.py).
It enumerated serial ports immediately and every two seconds, filtering USB
candidates by Espressif VID/PID `303a:1001`. These are candidates, not verified
Axioms. At that stage it did not open ports, connect boards or publish sensor
data. Background verification was added in the next increment below.

With no candidates, it logs `Waiting for an Axiom...` once and stays alive.
It logs again only when the candidate set or enumeration error changes. Candidate
ordering alone does not trigger another message. Enumeration errors are reported
without stopping the node, and Ctrl+C releases the node and ROS context.

[Discovery tests](../src/axiom_driver/test/test_usb_discovery.py) cover the real
timer, candidate filtering and transitions, enumeration recovery, shutdown and
the installed console entry point without opening physical ports. The user later
confirmed waiting, shutdown and candidate plug/unplug behaviour on Pi/Kilted.

## Next increment: background firmware verification

The node now submits newly seen candidates to one background worker. The
[probe helper](../src/axiom_driver/axiom_driver/core/discovery.py) opens a serial
session, obtains the existing `v` response and closes the session in `finally`.
Recognition checks only a successful `rslt` and a string `SystemName` beginning
with `Axiom`. This prefix is a firmware naming convention, not an immutable
hardware property. Version and MAC fields do not gate recognition.

The ROS timer collects completed results. Recognised and unrecognised replies
are checked once per observed appearance. Probe exceptions become eligible for
another attempt on the first successful scan at least five seconds after the
failure is collected. A pending probe prevents overlapping submissions for that
port. Repeated identical failures stay quiet; the first or a changed error is
logged, and successful recognition is reported normally.

Removed ports lose their previous check, retry deadline and error message;
queued probes are cancelled and late results from removed attempts are discarded.
Single-board sensor driver startup was added in the following increment below.
Existing launches and standalone bridge parameter defaults remain unchanged.

On shutdown, the timer stops, queued work is cancelled and the worker finishes
its active probe before the node is destroyed. Tests use controlled probes and
virtual serial peers rather than physical hardware. The user completed Pi/Kilted
acceptance for the worker; acceptance of the subsequent retry change is pending.

## Measurement output: original proposal

The investigation and proposal below predate implementation. The first
measurement increment is now implemented using existing descriptors; see the
2026-10-16 Illuminance/scalar validation entry below and the current
[output contracts](../src/axiom_driver/README.md#descriptor-driven-light-and-scalar-outputs).

### Current path to understand

```text
firmware descriptor (resp.a)
  -> core/attributes.py: binary fields and engineering scaling
  -> core/decoding.py: value, unit, SI conversion and validity
  -> core/pipeline.py: per-device sample and timestamp
  -> ros_adapters.py: ROS messages and topic suffixes
  -> publisher_cache.py: publisher creation and retirement
```

Start by reading:

- [LTR-390 descriptor fixture](../src/axiom_driver/test/fixtures/firmware_catalogue.json)
  (find the `LTR-390` record).
- [Decoder](../src/axiom_driver/axiom_driver/core/decoding.py) and
  [unit conversion](../src/axiom_driver/axiom_driver/core/units.py).
- [ROS adapters](../src/axiom_driver/axiom_driver/ros_adapters.py).
- [Firmware contract tests](../src/axiom_driver/test/test_firmware_contract.py),
  [ROS integration tests](../src/axiom_driver/test/test_ros_integration.py) and
  [hot-plug tests](../src/axiom_driver/test/test_hotplug_ros.py).

### Reproduced current behaviour

The five-byte payload `7d 00 00 30 00` with the checked-in LTR-390 descriptor
decodes to `ambient = 100 lux` and `UVI = 2 index`. Ambient has an SI value;
`index` currently has no normalised value/unit. Both readings appear in generic
JSON outputs; neither has a dedicated numeric ROS publisher.

This is synthetic payload evidence, not proof of the sensor's physical accuracy.
The decoder has already applied the descriptor divisors. A ROS mapping must not
apply those divisors again or publish the raw counters as engineering values.

### Proposed contract to agree before coding

- Publish the `ambient` quantity as `sensor_msgs/msg/Illuminance`, in lux, with
  the existing sample timestamp and sensor frame. Unknown variance is zero.
- Publish UVI through an agreed numeric fallback, provisionally
  `std_msgs/msg/Float64`, using its dimensionless engineering index. Do not
  convert it to lux or manufacture a physical SI unit.
- Select mappings from measurement metadata, quantity and shape rather than a
  branch that recognises only the string `LTR-390`.
- Preserve existing topic identities and suffixes in this milestone. Naming is
  a separate change. Agree whether `UVI` is preserved verbatim or normalised
  before writing topic assertions.
- Preserve the current `sample` and `data` outputs for compatibility in M1.
- A missing or unsupported attribute must not prevent other valid measurements
  from being published. Do not flatten thermal/distance images into scalar topics.
- Existing IMU, range, thermal and multi-board behaviour must continue to work.

Decide these details first:

| Question | Proposed direction / decision needed |
|---|---|
| Which standard messages take priority? | Prefer semantic messages such as Illuminance, Temperature and Range when the quantity is known. Scalar fallback is for remaining attributes. |
| Which attributes get scalar fallback? | Agree whether attributes already represented in a semantic message are omitted from fallback, and how flags, counters and unitless values are handled. |
| What happens to unknown units? | Preserve the distinction between raw, engineering and normalised values. Do not silently label unknown-unit values as SI. Agree the fallback and metadata contract. |
| How are invalid readings represented? | Agree NaN versus suppression for each message contract; retain validity in metadata/generic outputs and avoid stale values masquerading as new samples. |
| Are headerless fallback messages acceptable? | Float64 has no timestamp, frame or unit fields. Document that limit and retain the timestamped generic output; do not invent a custom message without discussing the tradeoff. |
| What does the custom-message switch mean? | It currently leaves DeviceSample and ThermalGrid enabled. Decide its future meaning separately; do not silently change it during M1. |

### Small implementation steps

1. Explain the current LTR-390 path and agree on the contract above.
2. First add a passing decoder regression for LTR-390 engineering scaling, using
   the existing `decode()` test helper and the five-byte payload above. This
   establishes that correct values already reach the ROS adaptation boundary.
   Then add focused failing tests for the agreed missing normalisation/message
   behaviour. Cover a second compatible descriptor so that the result is not a
   sensor-name special case.
3. Implement the smallest change that satisfies those tests. Review it before
   expanding to additional quantities or introducing a general mapping schema.
4. Verify numeric message delivery using generated ROS messages and a firmware
   peer; verify publisher retirement and reappearance. Check existing sensors
   and board isolation.
5. Update the sensor-topic reference with actual behaviour, record evidence and
   make a focused commit after the existing work is accounted for.

## Validation workflow

Start with the smallest relevant tests. For the current decoder/configuration
baseline, from the repository root:

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
  src/axiom_driver/test/test_board_config.py \
  src/axiom_driver/test/test_firmware_contract.py \
  src/axiom_driver/test/test_commands_aliases.py \
  src/axiom_driver/test/test_pipeline.py
```

These tests need Python test dependencies; see [validation](validation.md).
They do not verify ROS publisher delivery. For ROS adapter changes, build and run
the relevant ROS integration tests in a sourced, isolated ROS environment before
running the broader build/test check:

```bash
./scripts/validate_ros.sh
```

That script uses Docker, installs dependencies and validates ROS Jazzy by default.
It mounts the repository read-only. Do not treat a passing Jazzy container run as
a fresh Kilted/Pi or physical hardware result. Coordinate any test that opens a
real Axiom; do not compete with a running driver or browser acquisition session.

## Decision record

| Date | Decision | Reason |
|---|---|---|
| 2026-10-16 | User implements; assistant provides guidance/review. | Keep the development hands-on and understandable. |
| 2026-10-16 | Work on `main`; preparation changes documentation only. | Explicit user instruction. |
| 2026-10-16 | Preserve all existing local edits. | Their disposition has not been authorised; keep them separate from new feature work. |
| 2026-10-16 | Initial changes stay in the host repository. | Startup, topic presentation and host message adaptation do not require Raft library changes. |
| 2026-10-16 | Start with startup and USB discovery; user implements, assistant writes and runs tests. | Follow the feedback order and keep implementation hands-on. |

## Development log

### 2026-10-16: preparation

- Fetched `origin/main` and verified it matches the local commit.
- Inspected and classified all 29 pre-existing modified files.
- Prepared this plan. No implementation, parameter defaults, runtime configuration,
  firmware, Git index or existing source files were changed.
- Python 3.13.1 baseline: **82 passed**, including driver contract, pipeline,
  session, virtual serial, aliases, board configuration, grid, machine environment
  and Mac adapter tests. Two WebSocket deprecation warnings; no failures.
  Reproduction command:

  ```bash
  PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider \
    src/axiom_driver/test/test_firmware_contract.py \
    src/axiom_driver/test/test_pipeline.py \
    src/axiom_driver/test/test_session.py \
    src/axiom_driver/test/test_serial_integration.py \
    src/axiom_driver/test/test_commands_aliases.py \
    src/axiom_driver/test/test_board_config.py \
    src/axiom_driver/test/test_grids.py \
    scripts/test/test_machine_env.py \
    examples/scenarios-dashboard/platforms/macos/test_host_runtime.py \
    examples/scenarios-dashboard/platforms/macos/test_session_reset.py \
    examples/scenarios-dashboard/platforms/macos/test_usb_ws_relay.py
  ```

- Clean ROS Jazzy baseline: **all seven packages built; 119 tests, zero errors,
  zero failures, four existing skips**. Source mounted read-only into a disposable
  container, using the existing `axiom-shake-lab:jazzy` image
  (`sha256:95e851befc5305089973f77447199792c93e9970faae05290b3a1b9b9be2a8d6`).
  ROS domain 86 with localhost discovery; no physical devices passed through.
  Reproduction command for a host with this image available:

  ```bash
  docker run --rm \
    -e ROS_DOMAIN_ID=86 -e ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
    -e PYTHONDONTWRITEBYTECODE=1 -e 'PYTEST_ADDOPTS=-p no:cacheprovider' \
    -v "$PWD:/work:ro" -w /tmp/axiom-development-baseline \
    axiom-shake-lab:jazzy bash -lc 'set -eo pipefail
  source /opt/ros/jazzy/setup.bash
  colcon build --base-paths /work/src
  source install/setup.bash
  colcon test --base-paths /work/src --event-handlers console_direct+ --return-code-on-test-failure
  colcon test-result --verbose'
  ```

  The tag alone is mutable; compare its image ID with the recorded value when
  reproducing this exact baseline. The generic validation script above builds
  from its own default image and installs dependencies afresh.
- These results cover the recorded commit plus the preserved local edits. The
  suites overlap; their counts must not be summed as unique tests. No fresh
  Pi/Kilted, graphical desktop or physical sensor acceptance was performed.
- After the user reviewed the changes and authorised publishing them, committed
  the existing demo work and formatting separately, followed by this plan. This
  establishes the baseline on `main`; no new feature code was written.
- The original LTR-390-first proposal was superseded by the user's decision to
  start with startup and USB discovery.

### 2026-10-16: USB waiting increment

- Nikos implemented the discovery node and its `setup.py` console entry, then
  corrected the functional issues identified in review. The assistant added the
  tests and cleaned up formatting after announcing those changes.
- Clean ROS Jazzy container validation: **all seven packages built; 130 tests,
  zero errors, zero failures, four existing skips**. All 11 discovery test cases
  passed. The image and isolation settings match the baseline recorded above;
  no physical devices were passed through.
- An installed `ros2 run axiom_driver axiom_usb_discovery` smoke check logged the
  waiting message once, stayed alive across repeated scans and exited with code
  zero on SIGINT without a traceback.
- No Pi/Kilted or physical USB acceptance has been performed. Next: the user
  pulls and builds on the Pi, runs the discovery tests and checks quiet waiting
  and Ctrl+C with no USB Axioms connected. Board verification and connection are
  later increments.

### 2026-10-16: background USB verification

- The user verified the initial waiting increment on Pi/Kilted: all 11 tests
  passed, waiting was quiet, Ctrl+C was clean, and USB plug/unplug transitions
  were reported correctly. A manual `v` handshake also succeeded once the host
  driver holding the serial port was stopped.
- Nikos implemented `is_axiom_firmware`, `probe_axiom_firmware` and the background
  worker. The assistant reviewed them, added tests, corrected the misspelled
  set operation and missing attribute underscore, fixed submission indentation,
  and cleaned up formatting. No architecture changes were required.
- Fresh ROS Jazzy container validation against `a1aa6cb` plus this increment:
  **all seven packages built; 177 tests, zero errors, zero failures, four existing
  skips**. ROS lint passed. Source was mounted read-only, domain 86 used Fast DDS
  with localhost discovery, and no physical devices were passed through.
- All 21 discovery-node cases passed, including real ROS callback responsiveness,
  single-worker shutdown, duplicate prevention, multiple candidates, replug,
  stale-result rejection and enumeration recovery. Helper and virtual serial
  tests cover recognition, timeout/error propagation and session cleanup.
- Next: the user pulls, builds and runs the worker tests on Pi/Kilted, then
  checks background verification and unplug/replug using an otherwise unused
  Axiom serial port. This increment verifies candidates without starting sensor
  acquisition.

### 2026-10-16: simple failed-probe retries

- The user completed acceptance of `bd8711d` on Pi/Kilted: all 62 discovery,
  recognition and serial tests passed; a connected Axiom was verified once,
  unplug/replug triggered fresh verification and Ctrl+C exited cleanly.
- At the user's request, the assistant added a fixed five-second retry using
  the existing scan timer and worker. One per-port record stores a monotonic
  deadline and last error. Only exceptions retry; recognised and unrecognised
  replies remain checked until removal. Identical errors are suppressed and
  unplug/replug clears the retry state. No extra threads, timers or configuration
  options were added.
- Added controlled-clock coverage for the retry boundary, recovery, other-board
  isolation, in-flight duplicate prevention, warning suppression, removal,
  enumeration recovery and stale failures.
- Fresh Linux/Jazzy validation against `bd8711d` plus this increment: **all seven
  packages built; 184 tests, zero errors, zero failures, four existing skips**.
  All 28 discovery-node cases and ROS lint passed. Source was mounted read-only,
  domain 86 used Fast DDS with localhost discovery, and no physical devices were
  passed through.
- The user explicitly chose to skip the Pi/Kilted retry check and proceed to
  automatic driver startup. This retry increment has Linux/Jazzy validation only.

### 2026-10-16: single-board driver factory

- Nikos added `_create_driver(port)`, which creates the existing host bridge in
  `/axiom` using the discovery node's ROS context. It selects the supplied serial
  port and enables automatic connection, reconnection and acquisition. Global
  ROS arguments are ignored for the child so discovery-node options do not
  override that configuration.
- Review found no functional correction needed. The assistant reordered the
  imports, capitalised Axiom in the docstring and added two tests: actual ROS
  configuration/context isolation with conflicting global arguments, and serial
  handshake plus acquisition subscription against a virtual firmware peer once
  the returned driver is explicitly added to an executor.
- Fresh Linux/Jazzy validation against `62cd98a` plus this increment: **all seven
  packages built; 186 tests, zero errors, zero failures, four existing skips**.
  ROS lint passed. Source was mounted read-only, domain 86 used Fast DDS with
  localhost discovery, and no physical devices were passed through. No Pi/Kilted
  or physical USB validation was performed for this increment.
- At this stage, the helper was not yet called by discovery. Registering the
  returned driver with an executor and managing its lifetime were left for the
  next increment; fixed `/axiom` naming targets one board.

### 2026-10-16: discovery owns the single-board host driver

- Nikos wired successful verification into `_start_driver`, which registers one
  bridge with discovery's executor. Removing its USB port detaches and destroys
  that bridge before any replacement is started. Reappearance requires a fresh
  verification, including when the OS assigns a different serial path.
- The entry point now explicitly runs a `SingleThreadedExecutor`. Discovery and
  bridge ROS callbacks run sequentially; probing, connection and decoding retain
  their existing workers. Shutdown stops the executor, then cancels scanning,
  destroys the managed bridge, finishes probe cleanup and releases ROS resources.
- The assistant corrected `get_logger().ino` to `.info`, `_stop_Driver` to
  `_stop_driver`, removed duplicated removal code and cleaned up whitespace.
  No design changes were needed for this single-board increment.
- Updated tests for one-time driver registration, non-Axiom/failed probes,
  unplug/replug, changed port paths, enumeration failures, failed registration,
  cleanup ordering and executor shutdown. Real ROS/virtual serial coverage now
  exercises discovery's actual probe-to-driver handoff and replug, asserting
  that serial owners never overlap and that shutdown closes the connection.
- Fresh Linux/Jazzy validation against `62cd98a` plus the factory and lifecycle
  increments: **all seven packages built; 193 tests, zero errors, zero failures,
  four existing skips**. All 36 discovery cases and ROS lint passed. The source
  was mounted read-only, domain 86 used Fast DDS with localhost discovery, and
  no physical devices were passed through. No Pi/Kilted or physical USB
  acceptance was performed for these increments.
- An installed `ros2 run axiom_driver axiom_usb_discovery` smoke check stayed
  alive across empty scans, logged waiting once and exited with code zero on
  SIGINT without a traceback.
- Only one bridge under `/axiom` is managed. Additional verified boards do not
  replace the active driver; automatic selection of an already-checked second
  board after the first disappears and independent multi-board namespaces remain
  future work. This increment should be tested with one Axiom connected.

For later entries, record: objective, behaviour/decision, changed files, tests and
environment, hardware evidence (if any), commit and remaining issues. Add entries
when a meaningful increment finishes or a decision changes.

### 2026-10-16: complete the startup feedback

- The user delegated the remaining startup work to the assistant. The normal
  launch is now `ros2 launch axiom_driver axiom.launch.py`, requiring no board
  file, USB path or IP. Connection, acquisition and recovery default to enabled;
  all three flags can still be disabled for explicit manual operation.
- Discovery manages one bridge per firmware MAC with stable `/axiom_<MAC>` names
  and distinct frames. It re-verifies removed/reappearing endpoints, discards late
  probes, retries exceptions and keeps other boards running independently.
- Wi-Fi uses the existing Raft HTTP mDNS advertisement and a non-acquiring
  `/api/v` check. USB wins over Wi-Fi for the same identity; transport changes
  preserve namespace, manual disconnect and requested acquisition rate. The old
  USB-only executable remains available. Firmware and Raft libraries were untouched.
- Optional `id` rules extend the existing board-file format, applying names,
  frames, aliases and driver parameters. Explicit endpoints still work. Setting
  `discovery.include_unconfigured: false` selects a robot's boards on shared LANs;
  ROS domains remain a host/process setting. Endpoint-only rules retain their
  transport restrictions after a matching board's other transport remains visible.
- Host sessions take per-user nonblocking endpoint and board locks. Probes claim
  the serial endpoint but do not claim acquisition ownership; otherwise a live
  Wi-Fi owner would prevent discovering its USB alternative. Discovery also checks
  reconnected firmware identity before acquisition. Locks are advisory on one
  computer; they cannot coordinate other computers or unrelated/older clients.
- Updated the normal quick start, driver reference, sample configurations,
  visualization walkthroughs, tmux guidance and clean validation dependencies.
  Published wiki sources were prepared from these generic repository instructions.
- Final Linux/Jazzy container result: **all seven packages built; 229 tests,
  zero errors, zero failures, four existing skips**. Pi/Kilted: the same result
  after an isolated rerun of the unchanged teaching-demo package. That replay
  test intermittently lost samples/events on the Pi; no assertion was weakened
  and no teaching-demo runtime code changed. The startup tests passed. A separate
  host configuration/helper suite passed **17 tests**.
- Actual Pi hardware: host firmware `0.1.19-devlib-host`, a physical Axiom on USB
  and its mDNS-discovered Wi-Fi endpoint. Verified automatic acquisition, an IMU
  alias, a distinct configured frame prefix, stable identity, USB-to-Wi-Fi fallback,
  return to USB, one acquisition owner and retained manual stop/disconnect. Received
  362 IMU messages and 45 raw packets; the short USB observation measured about
  62 IMU messages/s. This is a received-rate observation, not a timing benchmark.
- USB appearance/removal in the automated hardware check was controlled at the
  discovery enumerator boundary while the cable stayed attached. Virtual serial
  tests cover changed device paths; no physical cable/power-cycle claim is made.
  Pi validation ran in a separate temporary workspace and ROS domain 87.
- Validation logs: `/tmp/axiom-auto-startup-final-jazzy.log` on the Mac and
  `/tmp/axiom-auto-startup-kilted-tests.log`,
  `/tmp/axiom-auto-startup-kilted-teaching-recheck.log` and
  `/tmp/axiom-real-startup-result.json` on the Pi.

### 2026-10-16: final startup acceptance and publication

- Added an additional end-to-end check using two independent pseudo-terminal
  firmware peers and actual ROS bridges. Both acquire automatically; removing and
  replacing one at a different serial path preserves its namespace and leaves the
  other board's connection generation and acquisition unchanged. This closes the
  serial-specific multi-board acceptance check without requiring a second physical
  board or someone to move cables.
- Final fresh Linux/Jazzy build and full test run: **230 tests, zero errors,
  zero failures, four existing skips**. Final Pi/Kilted colcon results likewise
  report **230 tests, zero errors, zero failures, four skips**, after the driver
  package was rerun with the additional serial case. The previously noted
  intermittent teaching test was checked in isolation. Its source is unchanged.
  The final fresh Jazzy log is `/tmp/axiom-automatic-final-clean.log`; the Pi's
  final driver log is `/tmp/axiom-auto-startup-kilted-final-driver.log`.
- Committed and pushed the implementation as `b2dd9cc`. Updated and verified all
  six existing published ROS guide pages plus the new `automatic_startup` page,
  preserving their wiki revision history, images and tmux anchor. The repo and
  published instructions describe automatic startup and retain explicit manual
  operation. No firmware/Raft repository changes were made.
- Pulled and rebuilt the Pi's normal checkout. Its generated driver build/install
  artifacts required regeneration; the old artifacts and board file were backed
  up outside the checkout. Converted the known board's local `axiom1` entry to an
  identity rule while preserving its aliases/settings and the other board entry.
  Installed the mDNS dependency in the Pi user's Python site packages.
- The normal discovery launch is running in the existing tmux Terminal 1, with
  the existing Foxglove bridge preserved. A fresh ROS subscriber confirmed one
  connected USB owner under `/axiom1` and live IMU messages with its expected frame.
  The installed Kilted discovery executable also passed quiet empty scans and
  SIGINT exit with code zero and no traceback. Only one physical board was reachable;
  multi-board acceptance used independent firmware peers.

### 2026-10-16: additive readable sensor topics

- Added `<model>_b<bus>_<hex-address>/<output>` measurement paths with stable
  location identifiers, ROS-safe visible model names and separate payload groups.
  Descriptor-declared dual image capabilities retain `range/image` and
  `thermal/image`; ordinary image, IMU and thermal-grid suffixes are shortened.
- Preserved every legacy topic, configured alias/source, frame, message contract
  and command path. Exact configured alias paths take precedence. New topics
  inherit source QoS overrides unless explicitly overridden. Inventory retains
  `topic` and adds only emitted readable paths in `public_topics[group][source]`.
- Added **37 contract tests** and extended real DDS range/IMU/image, hot-plug,
  replacement, alias, lifecycle and demo-consumer checks. Linux/Jazzy container:
  all seven core packages built; **267 total tests: 263 passed, four existing
  skips, zero errors/failures**. Optional demo/dashboard packages built;
  **37 tests passed, two optional Marty-interface skips**. Installed launch
  argument checks and `git diff --check` passed.
- Review fixed hidden names for punctuation/Unicode-leading models. Initial
  lint findings (an incorrect working directory scanning generated files, then
  three test indentation errors) were resolved without weakening assertions.
  No physical Pi validation, firmware/Raft edits or externally published guide
  updates were performed. This naming increment remains uncommitted and unpushed.
- Final logs: `/tmp/axiom-topic-naming-colcon-final.log` and
  `/tmp/axiom-topic-naming-demo-tests.log` on the Mac.

### 2026-10-16: replace public topic names completely

- The user superseded additive compatibility: public measurements and descriptor
  commands now use only model/location sensor roots. There is no old-topic mode
  or QoS fallback. Raw bus/address identities, firmware requests and existing TF
  frame IDs are retained independently of topic names.
- Inventory `topic` is the new root, or `null` before metadata resolves;
  `public_topics` uses canonical new output suffixes. Alias paths remain user
  chosen, with `data_raw`, `grid` and `image` source selectors. Only actual dual
  image descriptors use the `range/image` and `thermal/image` exception.
- Migrated bundled monitors, visualizers, plotter filters, shake tools, dashboard
  discovery/commands, sensor-view subscriptions, configuration templates and
  current guides. Regenerated the existing Graphviz diagrams. Explicit viewer
  aliases keep their chosen paths with updated selectors; historical captures
  and dated validation records are retained as evidence.
- Runtime/consumer review and migrated tests confirm current-only publisher and
  descriptor-service paths, metadata resolution, alias routing, exact QoS keys,
  lifecycle, multi-board/group isolation and unchanged units/frames/timestamps.
  Viewer tests cover unresolved rows, first outputs after metadata and alias
  independence; dashboard tests cover alias deduplication, ambiguous cameras,
  nested namespaces and command flow. Synthetic MCAP files use the new default
  IMU topic and retain an explicit topic override.
- Final Linux/Jazzy container validation: all seven core packages built;
  **273 tests: 269 passed, four existing skips, zero errors/failures**. Optional
  demo/dashboard packages built; **42 passed, two optional Marty-interface skips**.
  Supplemental host/helpers: **23 passed**. All **five dashboard JavaScript test
  scripts**, package/changed-file lint and four installed launch-argument smoke
  checks passed. The unchanged teaching replay test passed both full runs.
- Initial findings were stale test expectations for removed `DeviceKey.topic`,
  formatting errors and JavaScript tests invoked from the wrong directory; all
  were resolved without weakening assertions. Review also aligned the reference
  graph's dual-adapter input with its canonical copied command. Final logs:
  `/tmp/axiom-topic-migration-colcon-final.log`,
  `/tmp/axiom-topic-migration-demo-tests-final.log`,
  `/tmp/axiom-topic-migration-helpers.log` and
  `/tmp/axiom-topic-migration-dashboard-js-final.log` on the Mac.
- These results supersede the preceding additive implementation's validation.
  Firmware/Raft, the physical Pi and published userguides remain untouched.
  Ignored local board configurations require alias-source migration before
  using this version. Physical Axiom/Pi validation remains pending.

### 2026-10-16: Illuminance and scalar fallbacks

- The user authorised implementing this increment in the host driver, with
  independent review and tests, without committing or pushing. Existing
  descriptors and their engineering/SI values drive the outputs; no new ROS
  mapping metadata or firmware/Raft changes are included.
- LTR-390 now exposes `ambient` as Illuminance in lux and `UVI` as Float64 in
  index units. The same light-name/lux rules apply to other compatible
  descriptors. Other numeric, boolean and text scalars use Float64, Bool and
  String. Generic timestamped `sample` and JSON `data` outputs are retained.
- Existing semantic adapters consume their represented attributes; arrays are
  not flattened. Invalid numbers publish NaN, invalid bool/text readings are
  omitted, attribute case is retained, unsafe/colliding names are escaped, and
  scalar suffixes can be selected by aliases. Inventory retains `public_topics`
  and adds `output_info` with each emitted canonical message type and unit.
- An independent reviewer found no actionable bugs or regressions and verified
  the final corrections for multiple distance/battery attributes, bracket text
  formats and output units. Their focused final validation passed 32 tests.
- Added **39 tests** covering existing descriptor scaling, SI/unknown-unit
  fallback, another compatible light sensor, invalid first readings, booleans,
  text, arrays, naming, aliases/QoS, revision/removal cleanup and real DDS
  Illuminance/UVI delivery with late-joining retained inventory.
- Final Linux/Jazzy build: all seven core packages built; **312 tests total,
  308 passed, four existing copyright skips, zero errors/failures**. Optional
  demo tests: **12 passed**. Dashboard tests run directly with pytest:
  **30 passed, two existing optional Marty-interface skips**. Its colcon/setuptools
  runner reported no tests, so direct pytest was used to execute the actual suite;
  no dashboard files were changed. Package lint and `git diff --check` passed.
- Evidence is retained under `/tmp/axiom-scalar-evidence` on the Mac. Validation
  used synthetic firmware peers and real ROS Jazzy messages/DDS, without physical
  Axiom or Pi/Kilted testing. Changes remain uncommitted and unpushed.
- The user subsequently authorised committing and pushing this increment to
  `main`. Physical Pi/Kilted acceptance remains pending.
