"""Read-only acceleration arrows for two explicitly chosen ROS IMU topics.

The separated display frames are a layout, not measured mounting transforms.
Only acceleration is shown: Marty does not report orientation or gyro data.
"""

import math
import time

from geometry_msgs.msg import Point, TransformStamped
import rclpy
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from rclpy.validate_full_topic_name import validate_full_topic_name
from sensor_msgs.msg import Imu
from std_msgs.msg import ColorRGBA
from tf2_ros import StaticTransformBroadcaster
from visualization_msgs.msg import Marker, MarkerArray

from .sensors import Reading, finite


class AccelerometerView(Node):
    def __init__(self, **kwargs):
        super().__init__("accelerometer_view", **kwargs)
        self.declare_parameter("axiom_topic", "", ParameterDescriptor(read_only=True))
        self.declare_parameter(
            "marty_topic", "/marty/imu/data_raw", ParameterDescriptor(read_only=True)
        )
        self.declare_parameter("axiom_label", "Axiom", ParameterDescriptor(read_only=True))
        self.declare_parameter("marty_label", "Marty", ParameterDescriptor(read_only=True))
        self.sources = []
        frames = []
        for name, x in (("Axiom", -0.30), ("Marty", 0.30)):
            topic = self.get_parameter(name.lower() + "_topic").value
            validate_full_topic_name(topic)
            frame_id = name.lower() + "_acceleration_display"
            label = self.get_parameter(name.lower() + "_label").value
            source = dict(name=label, topic=topic, frame=frame_id, reading=Reading())
            self.sources.append(source)
            self.create_subscription(
                Imu, topic, lambda msg, s=source: self._imu(s, msg), qos_profile_sensor_data
            )
            frame = TransformStamped(child_frame_id=frame_id)
            frame.header.frame_id = "accelerometer_view"
            frame.header.stamp = self.get_clock().now().to_msg()
            frame.transform.translation.x, frame.transform.translation.z = x, 0.35
            frame.transform.rotation.w = 1.0
            frames.append(frame)
        self.transforms = StaticTransformBroadcaster(self)
        self.transforms.sendTransform(frames)
        self.publisher = self.create_publisher(
            MarkerArray, "visualization/accelerometers", qos_profile_sensor_data
        )
        self.create_timer(0.1, self._tick)

    def _imu(self, source, msg):
        vector = msg.linear_acceleration
        values = (vector.x, vector.y, vector.z)
        valid = all(finite(v) for v in values) and msg.linear_acceleration_covariance[0] != -1
        stamp = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
        source["reading"].update(
            stamp,
            self.get_clock().now().nanoseconds,
            time.monotonic(),
            values if valid else None,
            "" if valid else "Acceleration unavailable",
        )

    def _marker(self, source, identifier, kind, color):
        marker = Marker()
        marker.header.frame_id = source["frame"]
        marker.header.stamp = self.get_clock().now().to_msg()
        marker.ns, marker.id, marker.type = source["name"], identifier, kind
        marker.pose.orientation.w = 1.0
        marker.color = ColorRGBA(r=color[0], g=color[1], b=color[2], a=1.0)
        marker.lifetime.nanosec = 400_000_000
        return marker

    def markers(self, now=None):
        now = time.monotonic() if now is None else now
        markers = []
        for source, color in zip(self.sources, ((0.12, 0.55, 0.52), (0.70, 0.38, 0.13))):
            for axis, axis_color in enumerate(
                ((0.8, 0.2, 0.2), (0.2, 0.65, 0.25), (0.2, 0.35, 0.8))
            ):
                marker = self._marker(source, axis, Marker.ARROW, axis_color)
                tip = [0.0, 0.0, 0.0]
                tip[axis] = 0.12
                marker.points = [Point(), Point(x=tip[0], y=tip[1], z=tip[2])]
                marker.scale.x, marker.scale.y, marker.scale.z = 0.006, 0.015, 0.02
                markers.append(marker)
            reading = source["reading"]
            values = reading.value if reading.fresh(now) else None
            arrow = self._marker(source, 3, Marker.ARROW, color)
            if values is None:
                arrow.action = Marker.DELETE
            else:
                arrow.points = [
                    Point(),
                    Point(x=values[0] * 0.025, y=values[1] * 0.025, z=values[2] * 0.025),
                ]
                arrow.scale.x, arrow.scale.y, arrow.scale.z = 0.013, 0.035, 0.06
            markers.append(arrow)
            state = "waiting" if reading.stamp_ns == 0 else "unavailable"
            if not self.count_publishers(source["topic"]):
                state = "no_publisher"
            label = self._marker(source, 4, Marker.TEXT_VIEW_FACING, color)
            label.pose.position.z, label.scale.z = 0.23, 0.04
            label.text = (
                source["name"]
                + "\n"
                + (
                    f"Acceleration:{math.hypot(*values):.2f}m/s^2"
                    if values is not None
                    else "Acceleration:" + state
                )
            )
            markers.append(label)
        return MarkerArray(markers=markers)

    def _tick(self):
        self.publisher.publish(self.markers())


def main(args=None):
    rclpy.init(args=args)
    node = AccelerometerView()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
