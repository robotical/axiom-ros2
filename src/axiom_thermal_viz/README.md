# axiom_thermal_viz

`axiom_thermal_viz` turns Celsius samples in `axiom_interfaces/msg/ThermalGrid`
into an RViz heatmap and pixel labels. For an AMG8833 camera, follow the complete
[four-terminal walkthrough](../../docs/thermal-camera.md) or the
[published RViz guide](https://userguides.robotical.io/axiom/ros2/thermal_camera).

## Features

- Subscribes to the `ThermalGrid` topic produced by `axiom_driver`.
- Maps temperature ranges to a colour gradient and publishes a `CUBE_LIST` marker.
- Publishes small temperature labels at the top-right of each measured pixel.
- Configurable topic names, scaling, alpha and fixed temperature ranges.
- Includes an RViz layout for the heatmap and pixel labels.

## Usage

Complete the [host-driver setup](../../README.md) first. The driver must be
connected and acquiring thermal data. Run build commands from the repository root,
stopping affected processes before rebuilding. Use a graphical desktop for RViz.
The scenarios dashboard is optional; for a standard Image panel use the
[Foxglove guide](../../examples/foxglove/README.md#thermal-camera-on-one-axiom).

1. Install dependencies and build the core packages:
   ```bash
   source scripts/setup_env.sh
   rosdep install --from-paths src --ignore-src -r -y
   colcon build --base-paths src --symlink-install
   source scripts/setup_env.sh
   ```
   Restart the driver, connect and enable acquisition using the README before
   continuing to topic inspection.
2. Find the topic ending in `/thermal/grid` using `ros2 topic list -t`, then
   start the visualiser with that exact path, replacing the placeholder:
   ```bash
   THERMAL_TOPIC='PASTE_DISCOVERED_THERMAL_GRID_TOPIC_HERE'
   ros2 run axiom_thermal_viz thermal_heatmap --ros-args \
     -r __ns:=/sensing \
     -p input_topic:="$THERMAL_TOPIC" \
     -p output_topic:=thermal_heatmap \
     -p use_dynamic_range:=false \
     -p min_temperature:=15.0 \
     -p max_temperature:=40.0
   ```
3. In another terminal at the repository root, source the environment and set the
   same camera topic. Read its frame ID and open the supplied RViz layout:
   ```bash
   source scripts/setup_env.sh
   THERMAL_TOPIC='PASTE_DISCOVERED_THERMAL_GRID_TOPIC_HERE'
   THERMAL_FRAME="$(ros2 topic echo "$THERMAL_TOPIC" \
     axiom_interfaces/msg/ThermalGrid --field header.frame_id \
     --qos-reliability best_effort --once | sed -n '1p')"
   ros2 run rviz2 rviz2 \
     -d "$(ros2 pkg prefix --share axiom_thermal_viz)/config/thermal.rviz" \
     -f "${THERMAL_FRAME:?No camera frame received}"
   ```

The layout subscribes to `/sensing/thermal_heatmap` (*Marker*) and
`/sensing/thermal_heatmap_labels` (*MarkerArray*). Temperatures are in °C; labels
refer to measured pixels even when the heatmap is interpolated. Set the topic and
read the frame in each terminal where they are used; shell variables are not shared
between panes. Pixel order is preserved. Cell size is a display layout, rather than
measured object size or position. Stop the adapter/RViz with Ctrl+C, then stop
acquisition and disconnect through the driver before stopping it.

### Parameters

| Parameter            | Default value                     | Description |
|----------------------|-----------------------------------|-------------|
| `input_topic` | `bus_1/device_169/thermal/grid` | Built-in relative example; override with the actual camera topic. |
| `output_topic`       | `thermal_heatmap`                 | Marker topic published for RViz. |
| `marker_namespace`   | `thermal_grid`                    | Namespace used for the marker message. |
| `cell_size`          | `0.02`                            | Side length (metres) of each base grid cell. |
| `interpolation_factor` | `1`                             | Bilinear upsampling factor for smoother visualisation (`1` keeps the raw grid). |
| `cell_height`        | `0.001`                           | Z scale (metres) of each cube marker. |
| `alpha`              | `0.95`                            | Alpha component applied to all cubes. |
| `min_temperature`    | `nan`                             | Fixed minimum (°C) for colour mapping. Ignored when `use_dynamic_range` is `true`. |
| `max_temperature`    | `nan`                             | Fixed maximum (°C) for colour mapping. Ignored when `use_dynamic_range` is `true`. |
| `use_dynamic_range`  | `true`                            | When `true`, derive colour scaling from each incoming frame. |
| `frame_fallback`     | `thermal_link`                    | Frame used if the incoming message has an empty frame id. |
| `show_temperatures`  | `true`                            | Publish per-pixel temperature labels on `<output_topic>_labels`. Setting it to `false` removes existing labels. |

## RViz Tips

- The default cube size works well for the 8×8 AMG8833 sensor. Reduce `cell_size` for denser sensors.
- To place the camera in a robot coordinate system, provide its actual mounting transform and select the appropriate Fixed Frame.
- Combine the marker layer with a camera image or mesh for additional context.
