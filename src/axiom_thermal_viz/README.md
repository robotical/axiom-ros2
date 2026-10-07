# axiom_thermal_viz

`axiom_thermal_viz` turns thermal samples from the AMG8833 (or any other device publishing `axiom_interfaces/ThermalGrid`) into an RViz heatmap by emitting a `visualization_msgs/Marker` stream.

## Features

- Subscribes to the `ThermalGrid` topic produced by `axiom_driver`.
- Maps temperature ranges to a colour gradient and publishes a `CUBE_LIST` marker.
- Publishes small temperature labels at the top-right of each measured pixel.
- Configurable topic names, scaling, alpha and fixed temperature ranges.

## Usage

1. Build the workspace to generate the custom message types:
   ```bash
   colcon build --packages-select axiom_interfaces axiom_driver axiom_thermal_viz
   ```
2. Source your overlay:
   ```bash
   . install/setup.bash
   ```
3. Launch the visualiser (update the topic if required):
   ```bash
   ros2 run axiom_thermal_viz thermal_heatmap --ros-args -p input_topic:=bus_1/device_169/thermal/grid
   ```
4. In RViz, add a *Marker* display pointed at the `thermal_heatmap` topic. Adjust the marker size/colour as desired.
5. Add a *MarkerArray* display for `thermal_heatmap_labels` to show pixel temperatures
   to one decimal place. Values are in °C; labels refer to measured pixels even
   when the heatmap is interpolated.

### Parameters

| Parameter            | Default value                     | Description |
|----------------------|-----------------------------------|-------------|
| `input_topic`        | `bus_1/device_169/thermal/grid`        | Source topic with `ThermalGrid` messages. |
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
- Enable *Use Frame Lock* in RViz if you expect the frame to move with the robot.
- Combine the marker layer with a camera image or mesh for additional context.
