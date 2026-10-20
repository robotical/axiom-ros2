# Lighting controls in RViz

The optional `axiom_light_panel` package adds an RViz panel for lights whose
descriptors advertise whole-light RGB, brightness and Off controls. The Robotical
32-pixel, four-tier LED Stick also offers stack patterns. The panel uses the host
driver's ROS interfaces and opens no USB connection. Start the driver first, with
the light's device profile installed on the board.

```bash
# Load the same ROS installation, workspace and domain as the running driver.
source scripts/setup_env.sh

# Open the saved layout; the selector discovers live lights on all boards.
ros2 launch axiom_light_panel lights.launch.py
```

Alternatively, add **Panels → Add New Panel → axiom_light_panel/LightPanel** to
an existing RViz layout. Build dependencies include Qt5 Widgets and RViz headers;
install declared dependencies with `rosdep install --from-paths src --ignore-src -r -y`.

Select a discovered light, then:

- **Choose colour** streams the latest RGB target. **Apply colour** returns to
  the selected colour after a pattern or Off, even if the colour hasn't changed.
- **Apply brightness** sends a value in 0–255 without stopping the pattern.
- **Apply stack pattern** sends four tier settings once. Rows appear top to bottom:
  red, amber, green, blue. Each supports Off, Steady, Flash or Opposite phase.
  The period is the base period multiplied by 1, 2, 4 or 8 for rate exponents 0–3.
- **Off** stops the pattern and clears the whole chain.

Colour and pixel writes stop an active pattern. A pixel write changes only that
pixel; the other pixels retain their last pattern frame. Controls show requested
settings. Service acknowledgements confirm driver processing, not physical output.
The module status line shows reported command/error counters, flags and brightness;
missing or old feedback is labelled unknown. Flag bit 2 (value 4) means pattern running.

Opening the panel, discovering a light or reconnecting sends no output commands.
Previous output is not replayed. Controls become unavailable when inventory is
lost/stale; use a fresh input after recovery. A timed-out request may have reached
the device, so check status before retrying. Closing RViz does not send Off: use
Off explicitly when finished. Brightness initially shows a proposed value of 64;
it is not a device readback and is sent only when Apply brightness is pressed.

## Headless ROS interfaces

Read the board's `devices` inventory for exact `command_topics` and `commands`
paths. Namespace and bus/address suffixes depend on your board and devices.

```bash
# Inspect commands; replace /axiom with your board namespace.
ros2 topic echo /axiom/devices std_msgs/msg/String --once \
  --qos-durability transient_local --qos-depth 1 --full-length

# Copy the full paths from that inventory into these variables.
COLOUR_TOPIC='PASTE_DISCOVERED_COLOUR_TOPIC_HERE'
STACK_SERVICE='PASTE_DISCOVERED_STACKLIGHT_SERVICE_HERE'
BRIGHTNESS_SERVICE='PASTE_DISCOVERED_BRIGHTNESS_SERVICE_HERE'
OFF_SERVICE='PASTE_DISCOVERED_OFF_SERVICE_HERE'

# Normalized RGB; alpha is ignored. This stops an active pattern.
ros2 topic pub --once "$COLOUR_TOPIC" std_msgs/msg/ColorRGBA \
  '{r: 1.0, g: 0.0, b: 0.0, a: 1.0}'

# Base milliseconds, then four bottom-first state bytes: alternating tiers.
ros2 service call "$STACK_SERVICE" axiom_interfaces/srv/DeviceCommand \
  '{values: [250, 2, 3, 2, 3]}'

# Brightness preserves the pattern; Off stops it and blanks every pixel.
ros2 service call "$BRIGHTNESS_SERVICE" axiom_interfaces/srv/DeviceCommand '{values: [64]}'
ros2 service call "$OFF_SERVICE" axiom_interfaces/srv/DeviceCommand '{values: []}'
```

The supported StackLight descriptor has `vt: stacklight`, `f: STACKLIGHT`,
`t: '>HBBBB'` and `NY: 4`. Base 0 selects 250 ms; explicit values must be
40–65535 ms. Each integer state is `mode | (rate << 2)`, mode and rate each 0–3;
reserved bits, fractional values and invalid periods are rejected. Other custom
formats remain unsupported. RGB inputs support the existing three-byte format
and packed `>I`/`06x` descriptors. The driver converts RGB to `0xRRGGBB`.

## Developer verification

Normal `colcon test` runs mock ROS/Qt tests, including failed/timed-out services,
stale inventory and no reconnect replay. It does not command physical lights.
The separate manual acceptance executable loads the real plugin into an RViz
`VisualizationFrame`, interacts with its Qt widgets and checks independent,
CRC-protected module readback through the driver's existing readback service.
It changes real output, then switches Off and restores the initial brightness.
Start the driver with a supported light before running it:

```bash
# Explicitly opt in to the physical test and save its results/screenshots.
AXIOM_LIGHT_HARDWARE=1 ./build/axiom_light_panel/light_hardware_acceptance \
  ./src/axiom_light_panel/config/lights.rviz /tmp/axiom-light-gui-evidence
```

This harness is not the stock `rviz2` executable. Check the normal launch separately
when validating packaging. Readback verifies module state; physical unplugging,
replacement and flash timing/appearance still need an operator's hardware check.
