# Axiom Spectrum: Foxglove panel extension

A small panel for a Robotical Sound Sensor's existing
`axiom_interfaces/msg/DeviceSample` topic. It draws coloured bars with frequency
labels and numeric dB readings. No ROS driver, interface, firmware or Raft
changes are needed. The panel does not depend on the older Foxglove user script.

## Build and install

Use Node.js 24 or later. From this directory:

```bash
npm ci
npm run typecheck
npm test
npm run package
```

The installable file is `dist/robotical.axiom-spectrum-0.1.0.foxe`.
In Foxglove's user profile menu, choose **Extensions → Install local extension…**
and select that file, or drag the `.foxe` file into an open visualization.
Install it on the computer running the viewer;
importing a layout JSON alone does not install an extension.

Use **Add panel → Axiom Spectrum**. Select the sound sensor's `sample` topic in
the panel's Source dropdown. Both canonical sensor topics and the optional
`/axiom1/sound/sample` alias work. The alias is the initial selection; it is not
required if you select the sensor's actual canonical topic instead.

For a spectrum-only dashboard, use **Layouts → Import from file…** and select
[one-axiom-spectrum.json](one-axiom-spectrum.json) from this directory, then open
the imported layout. Alternatively, add the panel to your existing sound layout
to keep its scalar plots alongside the bars. No ROS rebuild is required.

The **Spectrum scale** panel settings control the minimum and maximum dB. The
default range is −20 to 100 dB. Bars clip at those limits, while their numeric
labels and tooltips retain the actual measurement. Negative dB values are valid.
Colours distinguish frequencies; they do not indicate calibrated safety
thresholds. The dB reference and calibration remain properties of the sensor.

## Dummy data without ROS or hardware

```bash
npm run demo
```

Open `dist/axiom-spectrum-dummy.mcap` locally in Foxglove, add the panel, and
play the recording. It contains 45 seconds of explicitly synthetic samples:
speech-like levels, a bass-heavy spectrum, one invalid bin, a whole invalid
frame, malformed JSON, and recovery. All labels and attribute metadata use the
repository's sound descriptor fixture. This is a UI test fixture, not captured
audio or a hardware acceptance test. Generating it requires this repository's
fixture files; the installed extension itself has no such dependency.

## Input and display behaviour

- Reads already-decoded `bands.value` in dB from `values_json`; it never applies
  the firmware offset or divisor again and does not compute an FFT.
- Frequency labels come from `bands.meta.el`, with `bands.meta.eu: Hz`.
  Band count follows that descriptor, up to 64; frequencies are not hard-coded
  in the panel. Frequencies have equal visual spacing as categories.
- Invalid, nonnumeric and nonfinite bins show a dash and no coloured bar.
  Malformed input clears the old chart and shows an explanation.
- Playback seeks and topic changes clear previous readings. A sample more than
  five seconds behind Foxglove's current timeline is marked stale and dimmed.
  "Latest sample" describes the last received data, not a connection guarantee;
  paused or disconnected timelines may retain their last display.
- Topic selection and scale are saved in the layout. Multiple panels can select
  different sensors. Light/dark appearance follows Foxglove.
- It subscribes to data only: it sends no commands and starts no acquisition.

The eight existing sound layout/script tests remain separate:

```bash
node --test ../test_sound_demo.mjs
```

See the [sound walkthrough](../sound-demo.md) for host-driver and bridge setup,
and Foxglove's [extension installation guide](https://docs.foxglove.dev/docs/extensions/local-development).
