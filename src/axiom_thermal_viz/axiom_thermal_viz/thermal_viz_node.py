"""RViz heatmap visualizer for ThermalGrid data."""

from __future__ import annotations

from dataclasses import dataclass
import math
from typing import Iterable, List, Optional, Sequence, Tuple

from axiom_interfaces.msg import ThermalGrid
from geometry_msgs.msg import Point
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from std_msgs.msg import ColorRGBA
from visualization_msgs.msg import Marker, MarkerArray


@dataclass(frozen=True)
class ColorStop:
    position: float
    rgb: Tuple[float, float, float]


def clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


class ThermalGridVisualizer(Node):
    """Visualize ThermalGrid payloads as RViz heatmap markers."""

    _DEFAULT_COLOR_MAP: Tuple[ColorStop, ...] = (
        ColorStop(0.0, (0.231, 0.298, 0.753)),
        ColorStop(0.25, (0.266, 0.478, 0.914)),
        ColorStop(0.5, (0.482, 0.736, 0.934)),
        ColorStop(0.75, (0.905, 0.831, 0.298)),
        ColorStop(1.0, (0.706, 0.016, 0.150)),
    )

    def __init__(self) -> None:
        super().__init__('thermal_grid_visualizer')
        self.declare_parameter('input_topic', 'bus_1/device_169/thermal/grid')
        self.declare_parameter('output_topic', 'thermal_heatmap')
        self.declare_parameter('marker_namespace', 'thermal_grid')
        self.declare_parameter('cell_size', 0.02)
        self.declare_parameter('cell_height', 0.001)
        self.declare_parameter('alpha', 0.95)
        self.declare_parameter('min_temperature', float('nan'))
        self.declare_parameter('max_temperature', float('nan'))
        self.declare_parameter('use_dynamic_range', True)
        self.declare_parameter('frame_fallback', 'thermal_link')
        self.declare_parameter('interpolation_factor', 1)
        self.declare_parameter('show_temperatures', True)

        input_topic = self.get_parameter('input_topic').value
        output_topic = self.get_parameter('output_topic').value

        pub_qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        sub_qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)

        self._publisher = self.create_publisher(Marker, output_topic, pub_qos)
        self._label_publisher = self.create_publisher(
            MarkerArray, output_topic + '_labels', pub_qos
        )
        self._label_count = 0
        self._subscription = self.create_subscription(
            ThermalGrid,
            input_topic,
            self._handle_grid,
            sub_qos,
        )

        self.get_logger().info(
            f'Listening for ThermalGrid on {input_topic} '
            f'→ publishing heatmap markers on {output_topic}'
        )

    def _handle_grid(self, msg: ThermalGrid) -> None:
        width = int(msg.width)
        height = int(msg.height)
        total = width * height

        if total <= 0:
            self.get_logger().debug('ThermalGrid contains no samples; skipping publish')
            return

        temps = list(msg.temperature_c)
        if len(temps) < total:
            self.get_logger().warning(
                f'ThermalGrid sample mismatch: expected {total} points but received {len(temps)}'
            )
            return

        temps = temps[:total]

        min_fixed = self.get_parameter('min_temperature').value
        max_fixed = self.get_parameter('max_temperature').value
        use_dynamic = bool(self.get_parameter('use_dynamic_range').value)

        if use_dynamic or not self._valid_range(min_fixed, max_fixed):
            min_temp = min(temps)
            max_temp = max(temps)
        else:
            min_temp = float(min_fixed)
            max_temp = float(max_fixed)

        if not self._valid_range(min_temp, max_temp):
            min_temp = min(temps)
            max_temp = max(temps)
        if not self._valid_range(min_temp, max_temp):
            self.get_logger().debug('Unable to determine temperature range for color scaling')
            return

        interpolation = self._interpolation_factor(
            self.get_parameter('interpolation_factor').value
        )
        if interpolation > 1:
            temps, width, height = self._upsample_temperatures(temps, width, height, interpolation)

        marker = Marker()
        marker.header = msg.header
        if not marker.header.frame_id:
            marker.header.frame_id = self.get_parameter('frame_fallback').value
        marker.ns = self.get_parameter('marker_namespace').value
        marker.id = 0
        marker.type = Marker.CUBE_LIST
        marker.action = Marker.ADD

        base_cell_size = float(self.get_parameter('cell_size').value)
        cell_size = base_cell_size / interpolation if interpolation > 1 else base_cell_size
        cell_height = float(self.get_parameter('cell_height').value)
        marker.scale.x = cell_size
        marker.scale.y = cell_size
        marker.scale.z = cell_height
        marker.pose.orientation.w = 1.0

        alpha = clamp(float(self.get_parameter('alpha').value), 0.0, 1.0)

        marker.points = self._grid_points(width, height, cell_size)
        marker.colors = self._grid_colors(temps, min_temp, max_temp, alpha)

        marker.lifetime.sec = 0
        marker.lifetime.nanosec = 0

        self._publisher.publish(marker)
        # Labels always describe measured pixels, including when the heatmap is interpolated.
        self._publish_temperatures(
            marker, list(msg.temperature_c)[:total],
            int(msg.width), int(msg.height), base_cell_size, cell_height
        )

    def _publish_temperatures(
        self, grid: Marker, temperatures: Sequence[float],
        width: int, height: int, cell_size: float, cell_height: float
    ) -> None:
        labels = MarkerArray()
        namespace = grid.ns + '_temperatures'
        if self.get_parameter('show_temperatures').value:
            for index, (point, temperature) in enumerate(
                zip(self._grid_points(width, height, cell_size), temperatures)
            ):
                label = Marker()
                label.header = grid.header
                label.ns, label.id = namespace, index
                label.type, label.action = Marker.TEXT_VIEW_FACING, Marker.ADD
                # RViz centres text at its pose; these offsets keep it inside the top-right corner.
                label.pose.position = Point(x=point.x + cell_size * 0.20,
                                            y=point.y + cell_size * 0.34,
                                            z=cell_height / 2 + cell_size * 0.01)
                label.pose.orientation.w = 1.0
                label.scale.z = cell_size * 0.16
                label.color = ColorRGBA(r=1.0, g=1.0, b=1.0, a=1.0)
                label.text = f'{temperature:.1f}°'
                labels.markers.append(label)
        count = len(labels.markers)
        # Retire old IDs when the grid shrinks or labels are switched off.
        for index in range(count, self._label_count):
            label = Marker()
            label.header = grid.header
            label.ns, label.id, label.action = namespace, index, Marker.DELETE
            labels.markers.append(label)
        self._label_count = count
        self._label_publisher.publish(labels)

    def _grid_points(self, width: int, height: int, cell_size: float) -> List[Point]:
        half_w = width / 2.0
        half_h = height / 2.0
        points: List[Point] = []
        for row in range(height):
            y = (half_h - row - 0.5) * cell_size
            for col in range(width):
                x = (col - half_w + 0.5) * cell_size
                points.append(Point(x=x, y=y, z=0.0))
        return points

    def _grid_colors(
        self,
        temps: Sequence[float],
        min_temp: float,
        max_temp: float,
        alpha: float,
    ) -> List[ColorRGBA]:
        span = max_temp - min_temp
        if span <= 1e-6:
            span = 1e-6
        return [self._color_from_value((temp - min_temp) / span, alpha) for temp in temps]

    def _color_from_value(self, norm: float, alpha: float) -> ColorRGBA:
        norm = clamp(norm)
        for lower, upper in self._pairwise(self._DEFAULT_COLOR_MAP):
            if norm <= upper.position:
                fraction = (
                    0.0
                    if upper.position == lower.position
                    else (norm - lower.position) / (upper.position - lower.position)
                )
                return ColorRGBA(
                    r=self._lerp(lower.rgb[0], upper.rgb[0], fraction),
                    g=self._lerp(lower.rgb[1], upper.rgb[1], fraction),
                    b=self._lerp(lower.rgb[2], upper.rgb[2], fraction),
                    a=alpha,
                )
        last = self._DEFAULT_COLOR_MAP[-1]
        return ColorRGBA(r=last.rgb[0], g=last.rgb[1], b=last.rgb[2], a=alpha)

    @staticmethod
    def _pairwise(stops: Iterable[ColorStop]) -> Iterable[Tuple[ColorStop, ColorStop]]:
        iterator = iter(stops)
        try:
            prev = next(iterator)
        except StopIteration:
            return []
        pairs: List[Tuple[ColorStop, ColorStop]] = []
        for current in iterator:
            pairs.append((prev, current))
            prev = current
        if not pairs:
            pairs.append((prev, prev))
        return pairs

    @staticmethod
    def _lerp(a: float, b: float, t: float) -> float:
        return a + (b - a) * clamp(t)

    @staticmethod
    def _valid_range(lo: Optional[float], hi: Optional[float]) -> bool:
        if lo is None or hi is None:
            return False
        if any(val != val for val in (lo, hi)):  # NaN check
            return False
        return hi > lo

    @staticmethod
    def _interpolation_factor(raw_value: object) -> int:
        try:
            value = int(round(float(raw_value)))
        except (TypeError, ValueError):
            return 1
        if value < 1:
            return 1
        return value

    def _upsample_temperatures(
        self,
        temps: Sequence[float],
        width: int,
        height: int,
        factor: int,
    ) -> Tuple[List[float], int, int]:
        if factor <= 1 or width <= 0 or height <= 0:
            return list(temps), width, height

        rows: List[Sequence[float]] = [
            temps[row * width: (row + 1) * width] for row in range(height)
        ]

        new_width = width * factor
        new_height = height * factor
        upsampled: List[float] = [0.0] * (new_width * new_height)

        for new_row in range(new_height):
            if height == 1:
                src_y = 0.0
            else:
                src_y = (new_row / (new_height - 1)) * (height - 1) if new_height > 1 else 0.0
            y0 = int(math.floor(src_y))
            y1 = min(y0 + 1, height - 1)
            fy = clamp(src_y - y0, 0.0, 1.0)

            for new_col in range(new_width):
                if width == 1:
                    src_x = 0.0
                else:
                    src_x = (new_col / (new_width - 1)) * (width - 1) if new_width > 1 else 0.0
                x0 = int(math.floor(src_x))
                x1 = min(x0 + 1, width - 1)
                fx = clamp(src_x - x0, 0.0, 1.0)

                top = self._lerp(rows[y0][x0], rows[y0][x1], fx)
                bottom = self._lerp(rows[y1][x0], rows[y1][x1], fx)
                value = self._lerp(top, bottom, fy)

                upsampled[new_row * new_width + new_col] = value

        return upsampled, new_width, new_height


def main(args: Optional[Sequence[str]] = None) -> None:
    rclpy.init(args=args)
    node = ThermalGridVisualizer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


__all__ = ['ThermalGridVisualizer', 'main']
