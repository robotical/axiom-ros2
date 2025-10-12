"""RViz heatmap visualizer for ThermalGrid data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, List, Optional, Sequence, Tuple

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy

from axiom_interfaces.msg import ThermalGrid
from geometry_msgs.msg import Point
from std_msgs.msg import ColorRGBA
from visualization_msgs.msg import Marker

from rclpy.qos import DurabilityPolicy


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
        self.declare_parameter('input_topic', 'AMG8833_169/thermal/grid')
        self.declare_parameter('output_topic', 'thermal_heatmap')
        self.declare_parameter('marker_namespace', 'thermal_grid')
        self.declare_parameter('cell_size', 0.02)
        self.declare_parameter('cell_height', 0.001)
        self.declare_parameter('alpha', 0.95)
        self.declare_parameter('min_temperature', float('nan'))
        self.declare_parameter('max_temperature', float('nan'))
        self.declare_parameter('use_dynamic_range', True)
        self.declare_parameter('frame_fallback', 'thermal_link')

        input_topic = self.get_parameter('input_topic').value
        output_topic = self.get_parameter('output_topic').value
        
        pub_qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        sub_qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)

        self._publisher = self.create_publisher(Marker, output_topic, pub_qos)
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

        marker = Marker()
        marker.header = msg.header
        if not marker.header.frame_id:
            marker.header.frame_id = self.get_parameter('frame_fallback').value
        marker.ns = self.get_parameter('marker_namespace').value
        marker.id = 0
        marker.type = Marker.CUBE_LIST
        marker.action = Marker.ADD

        cell_size = float(self.get_parameter('cell_size').value)
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
        return [
            self._color_from_value((temp - min_temp) / span, alpha)
            for temp in temps
        ]

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


def main(args: Optional[Sequence[str]] = None) -> None:
    rclpy.init(args=args)
    node = ThermalGridVisualizer()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


__all__ = ['ThermalGridVisualizer', 'main']
 