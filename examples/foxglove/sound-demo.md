# Sound sensor in Foxglove

Import [one-axiom-sound.json](one-axiom-sound.json) to display all 15 scalar
attributes from a Robotical Sound Sensor and its latest nine frequency-band
levels. The spectrum user script is embedded in the layout: importing the JSON
also installs the script in that layout. No custom Foxglove extension is needed.
The readable source is [sound-spectrum.ts](sound-spectrum.ts).

For coloured bars with frequency labels instead of the built-in spectrum Plot,
install the optional [Axiom Spectrum panel](spectrum-panel/README.md). It reads
the same existing `sample` topic directly, without the user script or a separate
ROS `bands` topic. You can add it alongside these scalar plots or import its
spectrum-only layout. Host setup and acquisition are the same for both options.

## Prepare the host and select the sensor

Complete the repository's [host setup](../../README.md) and the
[Foxglove bridge installation](README.md#install-the-bridge-and-connect-a-viewer).
The host driver must include the descriptor-driven scalar outputs introduced in
commit `2e0c1f6`, or a later version. The sound sensor's firmware profile must
advertise type `RoboticalSoundSensor`, its scalar attributes, and the nine-band
`bands` attribute. The layout uses existing decoded data; it requires no firmware
change for that profile.

Use board key `axiom1` in `config/boards.yaml`, retaining your actual firmware
`id` or USB/Wi-Fi connection settings. Keep automatic connection, reconnection
and acquisition enabled as described in [automatic startup](../../docs/automatic-startup.md).
Merge these aliases into that board's existing `topic_aliases` mapping:

```yaml
axioms:
  axiom1:
    # Keep this board's existing identity/connection configuration here.
    topic_aliases:
      sound/sample:    {type: RoboticalSoundSensor, source: sample}
      sound/splSlow:   {type: RoboticalSoundSensor, source: splSlow}
      sound/splFast:   {type: RoboticalSoundSensor, source: splFast}
      sound/rms:       {type: RoboticalSoundSensor, source: rms}
      sound/peak:      {type: RoboticalSoundSensor, source: peak}
      sound/crest:     {type: RoboticalSoundSensor, source: crest}
      sound/zcr:       {type: RoboticalSoundSensor, source: zcr}
      sound/centroid:  {type: RoboticalSoundSensor, source: centroid}
      sound/spread:    {type: RoboticalSoundSensor, source: spread}
      sound/flatness:  {type: RoboticalSoundSensor, source: flatness}
      sound/rolloff85: {type: RoboticalSoundSensor, source: rolloff85}
      sound/flux:      {type: RoboticalSoundSensor, source: flux}
      sound/f0:        {type: RoboticalSoundSensor, source: f0}
      sound/seq:       {type: RoboticalSoundSensor, source: seq}
      sound/status:    {type: RoboticalSoundSensor, source: status}
      sound/clipCount: {type: RoboticalSoundSensor, source: clipCount}
```

This fragment is not a replacement board file. Each alias binds only when there
is exactly one matching online, fresh sensor with resolved metadata on that
board. If several sound sensors are connected, add the same `bus: '...'` and
`address: '...'` selectors to **every** sound alias. Copy their exact strings from
`/axiom1/devices`; firmware addresses are hexadecimal and may encode the slot as
well as the I2C address. The aliases and script must all select the same sensor.
Canonical model/location topics remain available alongside these aliases.

No ROS driver code changes are part of this layout. If your installed driver
predates scalar outputs, build and source the current checkout before starting
it. In a prepared terminal at the repository root:

```bash
source scripts/setup_env.sh
colcon build --base-paths src --symlink-install
source scripts/setup_env.sh
```

A layout or TypeScript-source update alone needs no ROS rebuild. Board alias
configuration changes require restarting the affected driver.

## Start the demo

The commands below run on the ROS host. Source `scripts/setup_env.sh` in each
terminal; use the same ROS domain and middleware settings throughout.

Terminal 1, start the driver:

```bash
source scripts/setup_env.sh
ros2 launch axiom_driver axiom.launch.py
```

Terminal 2, inspect the discovered device and its aliases:

```bash
source scripts/setup_env.sh
ros2 topic echo /axiom1/devices --once --qos-durability transient_local --full-length
ros2 topic info /axiom1/sound/splSlow
ros2 topic echo /axiom1/sound/splSlow --once --qos-reliability best_effort
ros2 topic echo /axiom1/sound/sample --once --qos-reliability best_effort --full-length
```

Expect `splSlow` to be `std_msgs/msg/Float64` with one publisher and a numeric
`data` field. The other 14 scalars also use Float64. `sample` is
`axiom_interfaces/msg/DeviceSample`; its `values_json` contains a `bands` entry
with `unit: "dB"`, nine decoded numbers in `value`, and validity information.
The sample header provides its timestamp and sensor frame. Inventory
`output_info` records the scalar message types and units.

Automatic startup connects and enables acquisition. An echo or Foxglove
subscription alone does not start it. To use a 5 Hz board publication rate for
this demo, optionally run in Terminal 2:

```bash
ros2 service call /axiom1/publish_data_subscription \
  axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 5.0}'
```

This changes delivery for the board, not the sound sensor's audio sampling or
spectral-analysis settings.

Terminal 3, start the bridge:

```bash
source scripts/setup_env.sh
ros2 launch foxglove_bridge foxglove_bridge_launch.xml
```

Open Foxglove and choose **Open connection → Foxglove WebSocket**. Connect to
`ws://localhost:8765` when the viewer runs on the ROS host, or
`ws://ROS_HOST_IP:8765` from another computer. Use the ROS host's address, not the
Axiom board's address. Connection/account prerequisites are covered in the
[bridge guide](README.md#install-the-bridge-and-connect-a-viewer).

## Import and use the layout

1. Copy `examples/foxglove/one-axiom-sound.json` to the viewer computer if the
   checkout is on another host. The script is already inside that JSON.
2. Open **Layouts → Import from file...**, select the JSON, then open the newly
   imported layout and save it as **Axiom: sound sensor**.
3. In the right sidebar's **User Scripts** tab, check that **Axiom sound spectrum**
   is present and has no errors once the sample topic is available. The script
   subscribes to `/axiom1/sound/sample` and produces
   `/foxglove_script/axiom1/sound/spectrum` inside Foxglove.
4. Speak or clap near the sensor and check that level plots and the spectrum
   update. Use different sounds to compare the distribution across bands; the
   display represents nine measured bands, not a full-resolution FFT.

The left column contains the guide, A-weighted levels, signal levels and sensor
status/counters. The right column contains the spectrum, spectral frequencies,
ratios and flux. Time plots use a sliding 30-second window and receipt time,
because Float64 messages have no header. Their aligned axes do not establish
hardware clock synchronisation.

| Plot | Attributes | Units |
|---|---|---|
| Sound pressure levels | `splSlow`, `splFast` | dBA |
| Signal levels | `rms`, `peak`, `crest` | dB |
| Spectral frequencies | `centroid`, `spread`, `rolloff85`, `f0` | Hz |
| Spectral ratios | `zcr`, `flatness` | Dimensionless, 0–1 |
| Spectral flux | `flux` | Firmware value, 0–255 |
| Sequence, status and clipping | `seq`, `status`, `clipCount` | Firmware values, 0–255 |
| Latest sound spectrum | `bands` from the sample JSON | dB against band index |

The spectrum uses Foxglove's **Array index** mode and the expression
`/foxglove_script/axiom1/sound/spectrum.bands_db[:]`. Each new sample replaces
the displayed spectrum. The frequency key is also shown in the guide panel:

| Index | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|
| Hz | 31.5 | 63 | 125 | 250 | 500 | 1000 | 2000 | 4000 | 8000 |

These positions follow the current sound descriptor's `bands.el` labels. The
script also exposes that order numerically as `frequency_hz` and retains the
original sample header. It does not apply the firmware's offsets/divisors again
or turn band levels into A-weighted readings. Calibration and the dB reference
remain properties of the sensor. Status is shown as its numeric bitmask; sequence
and clipping fields retain the firmware's 8-bit representation.

Invalid/nonfinite/null band readings become NaN gaps, including a whole invalid
frame. Malformed JSON, a missing band attribute, a non-nine-band profile, a
different unit, or another sensor type produces no script output. The script
keeps no history or cached readings. Foxglove can still retain the last displayed
frame when input stops or is skipped; check publisher count and inventory
freshness before treating it as a current reading.

The derived topic exists **only in Foxglove**. It is not a ROS publisher and will
not appear in `ros2 topic list`. The original `sample` retains everything needed
to reproduce the spectrum from a recording. This sensor output contains features
and band levels, so it cannot provide waveform playback in the Audio panel.

### Another board namespace or existing layout

The supplied aliases avoid changing scripts when the sensor moves between slots.
For a board namespace other than `axiom1`, replace every `/axiom1/` occurrence in
the JSON before import, including inside the embedded source and derived topic
paths. This also changes `/foxglove_script/axiom1/...`. Keep panel expressions,
the script's `inputs`, its `Input<...>` type and output topic consistent. Board
configuration must use the matching namespace.

To add the spectrum to another layout, create a User Script and paste
[sound-spectrum.ts](sound-spectrum.ts), adjusting both input-topic occurrences
and the output topic as needed. Add a Plot panel with **X-axis value type → Array
index** and the derived topic's `.bands_db[:]` field as Y. Editing the standalone
file does not update an imported layout; edit the script in Foxglove or update
the JSON's embedded `sourceCode`, then reimport. Replacing a JSON file on disk
does not change a layout already saved in Foxglove.

## Troubleshoot and finish

| Symptom | Check |
|---|---|
| No sound aliases | Board namespace, type `RoboticalSoundSensor`, sensor freshness, alias ambiguity and identical bus/address selectors |
| Generic sample exists, scalar topics absent | Build/source/restart a driver containing scalar outputs |
| ROS echoes work, plots are empty | Bridge host/domain, imported layout and the `/axiom1/sound/...` paths |
| Scalars update, spectrum does not | `sound/sample` alias, script errors, nine `bands.value` entries, `unit: "dB"`, validity and sensor type |
| Script reports an unknown input topic/type | Connect the data source and ensure the sample publisher is discovered; check both input-topic strings in the script |
| Derived topic absent from ROS CLI | Expected: it is local to Foxglove |
| Unexpected units or clipped trace | Inspect `output_info`; dBA/dB are separate, ratio/counter/flux axes are fixed, other vertical scales are automatic |
| Frozen spectrum | Check fresh samples and online inventory; Foxglove can retain the last frame after disconnect or rejected input |
| Old script or extra panels | Reimport and open the new layout; saved layouts do not follow file changes |

Stop the bridge in Terminal 3. In Terminal 2, stop publication and disconnect:

```bash
ros2 service call /axiom1/publish_data_subscription \
  axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 0.0}'
ros2 service call /axiom1/disconnect axiom_interfaces/srv/Disconnect '{}'
```

Then stop the driver in Terminal 1.

## Verification and references

Maintainers can run the focused script/layout checks with Node.js 24 or later:

```bash
node --test examples/foxglove/test_sound_demo.mjs
```

These checks cover descriptor frequency order and scalar coverage, embedded-source
consistency, decoded/negative values, invalid bins, malformed input and recovery.
They execute the TypeScript using Node's type stripping; they do not substitute
for Foxglove compilation, GUI rendering or a physical sensor acceptance run.
The SDK configuration, TypeScript and alias checks performed for this version are
recorded in [validation.md](../../docs/validation.md#foxglove-sound-layout--2026-10-16).

Official references:
[User Scripts](https://docs.foxglove.dev/docs/visualization/user-scripts),
[Plot panel](https://docs.foxglove.dev/docs/visualization/panels/plot),
[Layouts](https://docs.foxglove.dev/docs/visualization/layouts).
