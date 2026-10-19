# Axiom servo slider demo

Control one servo through the driver's direct angle-command topic using the same
`joint_state_publisher_gui` sliders as Marty. The GUI runs alongside RViz. The
GUI adapter publishes radian targets and calls an acknowledged enable service;
it does not open a second USB/Wi-Fi connection
or start another Axiom driver. No trajectory controller is required.

## Build and select a board

From the repository root on a ROS desktop:

```bash
source scripts/setup_env.sh
rosdep install --from-paths src --ignore-src -r -y
colcon build --base-paths src --packages-up-to axiom_servo_demo --symlink-install
source scripts/setup_env.sh
```

Keep the normal driver/discovery running in another prepared terminal:

```bash
ros2 launch axiom_driver axiom.launch.py
```

Find the board namespace and inspect its devices. Replace `/axiom` below with the
board's actual namespace, such as `/axiom_<firmware-MAC>`:

```bash
ros2 topic echo /axiom_discovery/boards --qos-durability transient_local --once
ros2 topic echo /axiom/devices --qos-durability transient_local --once
```

The adapter selects a device only when it is online, fresh, has resolved metadata
and advertises a radian `Float64` angle input in `command_topics` and a numeric
`enable` operation in `commands`. It does
not depend on a particular device type name. When several devices match, copy
the chosen row's exact `topic` into the `servo` launch argument. This is the
relative device root, without the board namespace.

The descriptor commands must use the driver's supported numeric formats. A
custom `vt` command format is not supported. Enable must accept both `0` and `1`.
The adapter uses the discovered angle topic, including any escaped action name.
`enable_command` selects an alternative enable/disable action name if needed.

## Start the slider

Choose demo limits appropriate to the attached mechanism. These limits apply to
both the GUI and the adapter; the driver enforces live descriptor limits.
The default range is −90° to +90°. The model is a schematic servo body and horn.
The demo enables the selected servo once on startup by default. For a visual-only
test without an enable request, append `start_enabled:=false`.

```bash
ros2 launch axiom_servo_demo servo_demo.launch.py \
  axiom_namespace:=/axiom \
  lower_limit_deg:=-90.0 upper_limit_deg:=90.0
```

To select one of several servos, append `servo:=PASTE_DEVICE_TOPIC_ROOT_HERE`.

The slider, `joint_commands` and driver angle topic all use ROS radians; limit
arguments remain degrees. The driver converts to the descriptor's units and
integer wire resolution. The old `angle_command` and `command_unit` launch
arguments and the angle service implementation have been removed.

The joint-slider window and RViz open together. RViz is labelled **Servo target
preview (not measured position)**: its model follows the GUI even when the
physical output is disarmed, disconnected or has not reached the target.

### Right-leg hip preview and live toggle

To use the hip model of a standalone Marty right leg, append `preview_model:=right_leg`:

```bash
# Show the right-leg hip while keeping the existing servo-control workflow.
ros2 launch axiom_servo_demo servo_demo.launch.py \
  axiom_namespace:=/axiom \
  preview_model:=right_leg \
  lower_limit_deg:=-15.0 upper_limit_deg:=15.0
```

The package includes only the right-leg URDF geometry and meshes, with no Marty
driver or separate Marty installation required. The same single `servo_joint`
slider drives the hip/thigh joint. Its parallel linkage follows through the URDF
mimic joints, whose calculated positions also appear in `joint_commands`;
the adapter uses only `servo_joint`. The knee and twist axes remain at neutral.
This still shows the requested target, not measured hardware position, and uses
the model's neutral pose and axis direction without calibrating the physical
servo's mounting.

**Toggle it while running:** in RViz's **Displays** panel, uncheck or check
**Right leg target preview (not measured position)**. This hides/shows the model
immediately while the slider and servo adapter keep running. Hiding the preview
does not disable the servo; use the acknowledged disable service below for that.

`preview_model:=servo` keeps the original schematic preview and is the default.
`rviz:=false` starts without an RViz window while keeping the joint-slider GUI.
The [asset notes](../src/axiom_servo_demo/meshes/marty_right_leg/README.md) record
the source revision, Apache-2.0 licence and model adaptations.

## Startup enable, movement and disable

`start_enabled` defaults to `true`. After selecting a compatible servo, the adapter
waits for a valid, fresh slider message and the enable service to become available.
It sends one enable request and waits for firmware acknowledgement before arming
angle commands. Wait for **Servo enabled; move the slider to send an angle**,
then move the slider. There is no separate enable command for this normal startup.

The initial slider position is a baseline: the adapter sends no angle on startup
or enable, including slider changes made while waiting for the acknowledgement.
Enable itself may energise the motor at its existing target according to firmware.
Use small changes first. The hardware may move directly to a new target; this
demo adds neither a trajectory nor a velocity ramp. The driver service response
confirms firmware acknowledgement, not physical completion.

With `start_enabled:=false`, the adapter stays disarmed until explicitly enabled.
For this mode, or to re-enable after a disconnect, failure or explicit disable,
wait for the slider and selected-device message, then run in a prepared terminal:

```bash
# Enable explicitly when startup enabling is off or a later re-enable is needed.
ros2 service call /servo_demo/set_enabled std_srvs/srv/SetBool '{data: true}'
```

Once the call succeeds, **move the slider** to send a new angle. Explicit enable
and disable requests cancel any pending automatic startup enable. A failed or
timed-out startup enable is not retried automatically.

Disable before stopping the demo:

```bash
# Disable the physical output and wait for acknowledgement before stopping.
ros2 service call /servo_demo/set_enabled std_srvs/srv/SetBool '{data: false}'
```

Wait for success, then stop the demo with Ctrl+C. A disable request immediately
stops new angle dispatch and sends disable after an outstanding request finishes
or times out. Stopping the GUI, losing a connection or killing the adapter does
not guarantee that hardware torque is disabled. Local disarming means that the
adapter stops sending angles; firmware disable is a separate acknowledged write.

## Inspect the ROS interfaces

```text
joint_state_publisher_gui → /servo_demo/joint_commands (JointState, radians)
                         → servo_adapter → driver's discovered Float64 angle topic
                           servo_adapter → discovered enable service

driver's servo joint_states → /servo_demo/observed_joint_states (JointState)
```

```bash
ros2 topic echo /servo_demo/status --qos-durability transient_local --once
ros2 topic echo /servo_demo/joint_commands --once
ros2 topic echo /servo_demo/observed_joint_states --once
```

`status` is retained JSON containing the selected servo root, local `armed` state,
`angle_unit: "rad"` and last status message. `set_enabled` returns an acknowledged
result. The adapter uses one outstanding enable/disable RPC and at most one pending
angle, replacing intermediate slider values with the latest target. It publishes
changed radian targets at up to `command_rate_hz` (default 10 Hz, maximum 50 Hz).
The driver owns descriptor conversion, latest-target coalescing, wire dispatch
and error diagnostics. Publishing an angle topic is not an acknowledgement.

Reported feedback is renamed to the demo's `servo_joint`; it is never filled in
from requested angles. The adapter listens to the selected device's
`<device-root>/joint_states` output. The driver currently creates that standard
output for `RoboticalServo` and `RoboticalSoloServo`. Another device type may
still support the angle topic and enable service without providing this feedback topic.
Whether firmware's reported angle represents measured position depends on the
board/servo implementation. No feedback is needed to move the slider.

## Reconnects and troubleshooting

Device removal, staleness, replacement, ambiguous selection or an inventory gap
longer than 2.5 seconds clears the selection and all pending angles. Slider input
older than one second or an enable/disable RPC failure disarms GUI output.
Angle-topic rejections are reported by the driver's diagnostics and logs; they
do not provide a per-message service response or change the GUI's local armed state.
A reconnect never automatically enables or replays the previous angle. Once
inventory and the slider are live again, call `set_enabled` and move the slider.
Losing the first selected device cancels startup enabling even if it had not yet
become ready. Starting a new demo process uses `start_enabled` again.

If selection keeps waiting, check `/axiom/devices` for `online`, `stale`,
`metadata_ready` and the advertised command names/descriptors. For rejected
angles, inspect driver diagnostics and both the configured and live limits. Matching
ROS domains and a sourced, rebuilt workspace are required in all terminals.

The launch defaults to using an already-running driver. For headless validation,
append `gui:=false rviz:=false start_enabled:=false`; publish valid `JointState`
messages to `/servo_demo/joint_commands` to supply input. The node's timeout parameters are
available through `ros2 run axiom_servo_demo servo_adapter --ros-args` for slower
links; the normal launch exposes board/command selection, limits and command rate.

Automated tests use synthetic inventories, real ROS topics/services and framed
mock firmware. They include the complete slider-adapter/driver command path.
Physical operation and the new controller board's live descriptor require
hardware acceptance. Stack lights are outside this slider demo.
