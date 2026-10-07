# Sensor demo validation

## Thermal camera scenario — 7 October 2026

- Added the manual one-Axiom AMG8833 walkthrough: connect, request acquisition,
  discover the thermal topic, inspect one grid, capture its frame, run the existing
  thermal visualizer and open the supplied RViz Marker configuration.
- Dashboard: **24 tests passed**, including namespace isolation, ambiguous cameras,
  subscriber-only topics and shell syntax. Seven packages built; the demo now
  declares its dependency on `axiom_thermal_viz`.
- An isolated DDS check (ROS domain 84) used a test-only 8×8 message publisher.
  The actual copied echo and frame commands succeeded, the existing adapter emitted
  64 coloured cubes in the input frame, and native RViz loaded the configuration
  and subscribed to `/sensing/thermal_heatmap`.
- Browser checks covered selection, terminal assignments, Copy confirmation,
  frame-command ⓘ details and navigation to the RViz step. The Linux guide is
  open on the scenario's first step with the four existing consoles preserved.
- Physical thermal camera validation remains pending. No device connection or
  firmware acquisition was started in the user's ROS domain.

Report: `../.validation/thermal-scenario-ros.log`.

### Live thermal display follow-up

- The physical AMG8833 at `/axiom/bus_1/device_169/thermal/grid` published 8×8
  frames with 64 finite pixel temperatures. The heatmap adapter published matching
  markers in `axiom_bus_1_device_169`.
- RViz was launched with an empty `-f` argument because `THERMAL_FRAME` was unset
  in that terminal. Its configured `thermal_link` frame could not receive the
  sensor markers. Setting its Fixed Frame to the incoming frame displayed the
  live camera grid.
- The RViz recipe now rejects an empty or unset frame variable with a clear shell
  error. Read thermal frame and the RViz command must run in the same terminal.
- **26 dashboard tests passed**, including both missing-frame cases. The guide
  was rebuilt and reloaded while the connected driver, heatmap and RViz stayed running.

### Pixel temperature labels

- The existing thermal visualizer publishes small `TEXT_VIEW_FACING` labels in a
  `MarkerArray` on `/sensing/thermal_heatmap_labels`. The RViz configuration includes
  that display. Labels show each measured pixel's temperature in °C to one decimal
  place, positioned inside the pixel's top-right corner.
- Three DDS tests passed: changing values and retiring removed pixels, removing
  labels when disabled, and preserving measured-pixel labels under interpolation.
- The physical camera produced 64 label markers with advancing timestamps in
  `axiom_bus_1_device_169`. Labels were checked visually in the current RViz session.
  Only the heatmap adapter was restarted; the driver and firmware acquisition continued.

## Guided scenario UI — 7 October 2026

- Saved the previous guide/workstation as local commit `b7a4172`, and the Marty
  driver as `ba82ea4`. Axiom was already committed at `65c5ba6`.
- Dashboard package rebuilt in ROS Jazzy; **21 dashboard tests passed**.
- JavaScript checks passed for graph rendering, reset, polling failure/recovery
  and scenario evidence: lingering subscribers, unplugged publishers, namespace
  isolation, stale connection state and unavailable discovery.
- Browser checks covered all eight scenarios: a single expanded step, manual
  navigation into cleanup, Copy confirmation without advancement, command and
  hardware ⓘ dialogs, Expand all / Collapse others, and independent Axiom nodes.
- The narrow Linux Firefox guide was checked beside four idle tmux panes. Runtime
  discovery contained only `/dashboard`; no driver or firmware acquisition started.
- No physical sensor validation was performed for this UI change. Endpoint counts
  are labelled as discovery evidence; console readings remain the data check.

## Sensor and driver checks — 6 October 2026

ROS 2 Jazzy / Ubuntu 24.04 in the optional Mac desktop adapter. The driver and
visualization packages also use normal ROS interfaces on native Linux.

## Physical USB Axiom

Board: Axiom018, firmware 0.1.16-devlib, USB `/dev/cu.usbmodem2101`.
Discovered LSM6DS (`bus_1/device_76a`) and VL53L4CD (`bus_1/device_129`).
The board remained powered during the user's distance-sensor unplug/reconnect.

- Connection and acquisition were started explicitly through ROS services.
- The existing `/axiom/range` subscriber stayed running throughout the swap.
- Its publisher count changed **1 → 0 → 1**. The sensor disappeared from inventory
  and returned, without restarting ROS or issuing another acquisition command.
- **1,285 finite range readings** were recorded, including readings after reconnection.
- The generated IMU `commands/set_sample_rate` service applied 52 Hz, with firmware
  confirmation of polling settings. Its original 104 Hz rate was restored.
- Actual acceleration was received through `/axiom/imu/data_raw` in m/s².
- Acquisition was explicitly stopped and the board disconnected after validation.

Raw observation: `../.validation/hotplug-hardware.json`.
The recorder `scripts/check_hotplug.py` only observes ROS inventory and range data;
it never connects the board or starts acquisition.

## ROS and protocol checks

- Driver: **59 passed, 1 existing copyright-header check skipped**. Includes real
  DDS publishers/services, socket firmware peers, descriptor encoding and validation,
  output-only discovery, offline/stale/replaced interfaces and alias ambiguity.
- The installed multi-board launch was executed with two independent firmware
  peers. Both drivers started disconnected, acquisition stayed off, frame prefixes
  differed, and each board could connect independently.
- Two-board hot swapping used identical sensor addresses in different namespaces.
  Removing or disconnecting one board left the other independent. LED brightness,
  pixel and off services sent the expected firmware bytes; invalid values sent none.
- Demo and optional guide: **27 passed**, including independent board status,
  namespace-specific recipes, live descriptor details, read-only discovery, sensor
  markers, dual accelerometers, HTTP/reset behavior and manual scenarios.
- Mac adapter: **14 passed**. JavaScript graph, network recovery, session reset,
  clipboard and Caps Lock checks passed. Ruff passed for the maintained demo code.
- Six ROS packages rebuilt successfully. Historical reaction/simulator nodes and
  executables were removed from the demo package.

Reports: `../.validation/driver-hotplug-tests.log`,
`../.validation/demo-hotplug-tests.log`, matching JUnit XML files, and
`../.validation/hotplug-build.log`.

Two physical Axioms and an LED/servo module were not available for this run.
Their connection and command paths were validated with firmware peers, not physical
actuation. The production guide has no simulator mode or automatic sensor controller.

## Workstation

The guide is optional. Launching drivers, echo and RViz is manual. Connection and
acquisition are manual except in the two-Axiom scenario described below.
The learning desktop opens the guide on the left and four empty tmux panes on the
right. The Start from scratch control and console reset command restart this
optional workstation without replaying ROS commands.

Browser checks confirmed the real board's topics and descriptor services in the
Running graph, information dialogs in both graphs, and exact command text from
Copy. The reset button completed successfully. Final ROS discovery contained only
`/dashboard`; all four tmux panes were empty bash consoles. Fresh desktop capture:
`../.validation/hotplug-workstation.jpg`.

## Two Axioms: USB, Wi-Fi and RViz

The scenario writes independent `/axiom/front` (USB) and `/axiom/rear` (Wi-Fi)
connections, with `auto_connect: true`, `autosub: true`, 20 Hz packet delivery
and `auto_reconnect: false`. Starting the launch attempts both connections and
requests acquisition. The guide only displays commands.

- **24 tests passed**: 20 guide tests and four DDS acceleration tests covering
  both the existing Axiom/Marty inputs and the two-Axiom topics and labels.
- A generated configuration was launched against two protocol peers in an
  isolated ROS domain. Both connected and sent the expected 20 Hz subscription
  without a connect or acquisition service call. This check did not access hardware.
- The read-only adapter labels the streams **Axiom USB** and **Axiom Wi-Fi**;
  valid vectors render independently, and stale/invalid input removes only its arrow.
- The scenario frees Terminals 3 and 4 after console inspection, then starts the
  adapter and RViz with fixed frame `accelerometer_view`. Both packages rebuilt,
  and Ruff passed for the changed Python files.
