"""Read-only RViz markers from real, discovered ROS sensor messages.

The two origins are a display layout, not measured sensor mounting transforms.
No robot commands, pose estimates, or synthetic sensor messages are produced.
"""

import json
import math
import time

from geometry_msgs.msg import Point, TransformStamped, Vector3
import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data
from rclpy.validate_full_topic_name import validate_full_topic_name
from sensor_msgs.msg import Imu, Range
from std_msgs.msg import ColorRGBA, String
from tf2_ros import StaticTransformBroadcaster
from visualization_msgs.msg import Marker, MarkerArray

from .sensors import Reading, finite, range_value


class SensorView(Node):
    def __init__(self, **kwargs):
        super().__init__("sensor_view", **kwargs)
        self.declare_parameter("axiom_namespace", "/axiom")
        self.declare_parameter("imu_sensor", "")
        self.declare_parameter("range_sensor", "")
        self.root = "/" + self.get_parameter("axiom_namespace").value.strip("/")
        self.devices = {}
        self.imu_source = ""
        self.range_source = ""
        self.connected = False
        self.inventory_seen = 0.0
        self.transforms = StaticTransformBroadcaster(self)
        frames = []
        for name, x in (("imu_view", -0.30), ("range_view", 0.30)):
            frame = TransformStamped(child_frame_id=name)
            frame.header.frame_id = "sensor_view"
            frame.header.stamp = self.get_clock().now().to_msg()
            frame.transform.translation = Vector3(x=x, z=0.35)
            frame.transform.rotation.w = 1.0
            frames.append(frame)
        self.transforms.sendTransform(frames)
        retained = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.create_subscription(String, self.root + "/devices", self._inventory, retained)
        self.publisher = self.create_publisher(
            MarkerArray, "visualization/markers", qos_profile_sensor_data
        )
        self.create_timer(0.1, self._tick)

    def _inventory(self, msg):
        try:
            rows = json.loads(msg.data)
            if not isinstance(rows, list) or len(rows) > 128:
                raise ValueError("Invalid inventory")
            for row in rows:
                topic = row["topic"]
                if not isinstance(topic, str) or not topic.startswith("bus_"):
                    raise ValueError("Invalid sensor topic")
                validate_full_topic_name(self.root + "/" + topic)
            topics = {
                row["topic"]
                for row in rows
                if row.get("online") and row.get("metadata_ready") and not row.get("stale")
            }
            rows = [row for row in rows if row["topic"] in topics]
            for topic in list(self.devices):
                if topic not in topics:
                    if self.imu_source == topic:
                        self.imu_source = ""
                    if self.range_source == topic:
                        self.range_source = ""
                    for sub in self.devices.pop(topic)["subscriptions"]:
                        self.destroy_subscription(sub)
            for row in rows:
                topic = row["topic"]
                if topic not in self.devices:
                    device = {"row": row, "imu": Reading(), "range": Reading(), "subscriptions": []}
                    self.devices[topic] = device
                    for suffix, kind, callback in (
                        ("imu/data_raw", Imu, self._imu),
                        ("range", Range, self._range),
                    ):
                        device["subscriptions"].append(
                            self.create_subscription(
                                kind,
                                self.root + "/" + topic + "/" + suffix,
                                lambda m, d=device, cb=callback: cb(d, m),
                                qos_profile_sensor_data,
                            )
                        )
                device = self.devices[topic]
                changed_type = row.get("type") != device["row"].get("type")
                if changed_type and self.imu_source == topic:
                    self.imu_source = ""
                if changed_type or not row.get("online") or not row.get("metadata_ready"):
                    device["imu"].reset()
                    device["range"].reset()
                device["row"] = row
            self.inventory_seen = time.monotonic()
            self.connected = bool(rows)
        except (KeyError, ValueError, TypeError):
            self.inventory_seen = 0.0
            self.connected = False

    def _ready(self, device, now):
        row = device["row"]
        return bool(
            self.connected
            and now - self.inventory_seen < 2.5
            and row.get("online")
            and row.get("metadata_ready")
            and not row.get("stale")
        )

    def _accept(self, device, kind, msg, value=None, error=""):
        now = time.monotonic()
        if self.devices.get(device["row"]["topic"]) is not device or not self._ready(device, now):
            device[kind].reset()
            return False
        stamp = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
        return device[kind].update(stamp, self.get_clock().now().nanoseconds, now, value, error)

    def _imu(self, device, msg):
        acceleration = msg.linear_acceleration
        gyro = msg.angular_velocity
        values = [acceleration.x, acceleration.y, acceleration.z, gyro.x, gyro.y, gyro.z]
        if not all(finite(v) for v in values) or msg.linear_acceleration_covariance[0] == -1:
            self._accept(device, "imu", msg, error="IMU measurement unavailable")
        else:
            self._accept(device, "imu", msg, values)

    def _range(self, device, msg):
        try:
            distance = range_value(msg.range, msg.min_range, msg.max_range)
            # The driver uses zero when the sensor profile has no FoV metadata.
            # Keep the measured distance; draw a ray rather than inventing a cone.
            fov = (
                msg.field_of_view
                if finite(msg.field_of_view) and 0 < msg.field_of_view < math.pi
                else 0.0
            )
            self._accept(device, "range", msg, (distance, fov))
        except ValueError as exc:
            self._accept(device, "range", msg, error=str(exc))

    def _reading(self, topic, kind, now):
        device = self.devices.get(topic)
        return (
            device[kind].value
            if device and self._ready(device, now) and device[kind].fresh(now)
            else None
        )

    def _marker(self, id, type, origin, color):
        marker = Marker()
        marker.header.frame_id = "sensor_view"
        marker.header.stamp = self.get_clock().now().to_msg()
        marker.ns, marker.id, marker.type = "sensors", id, type
        marker.pose.position = Point(x=float(origin[0]), y=float(origin[1]), z=float(origin[2]))
        marker.pose.orientation.w = 1.0
        marker.scale.x = marker.scale.y = marker.scale.z = 1.0
        marker.color = ColorRGBA(r=color[0], g=color[1], b=color[2], a=color[3])
        marker.lifetime.nanosec = 400_000_000
        return marker

    def _label(self, id, origin, text, available):
        # Avoid spaces at this scale: RViz issue ros2/rviz#1336 leaves them unscaled.
        color = (0.13, 0.22, 0.23, 1.0) if available else (0.52, 0.32, 0.14, 1.0)
        marker = self._marker(id, Marker.TEXT_VIEW_FACING, origin, color)
        marker.scale.z = 0.04
        marker.text = text
        return marker

    def markers(self, now=None):
        now = time.monotonic() if now is None else now
        for kind in ("imu", "range"):
            preferred = self.get_parameter(kind + "_sensor").value
            candidates = [
                topic
                for topic, device in self.devices.items()
                if self._ready(device, now) and device[kind].fresh(now)
            ]
            selected = preferred if preferred in candidates else ""
            if not preferred and len(candidates) == 1:
                selected = candidates[0]
            setattr(self, kind + "_source", selected)
        imu = self._reading(self.imu_source, "imu", now)
        distance = self._reading(self.range_source, "range", now)
        board = self.connected and now - self.inventory_seen < 2.5
        origins = [(-0.30, 0.0, 0.35), (0.30, 0.0, 0.35)]
        markers = []
        # Red/green/blue are each device's local X/Y/Z axes; spacing is display-only.
        for index, origin in enumerate(origins):
            for axis, color in enumerate(
                [(0.8, 0.2, 0.2, 1.0), (0.2, 0.65, 0.25, 1.0), (0.2, 0.35, 0.8, 1.0)]
            ):
                marker = self._marker(index * 3 + axis, Marker.ARROW, origin, color)
                tip = [0.0, 0.0, 0.0]
                tip[axis] = 0.12
                marker.points = [Point(), Point(x=tip[0], y=tip[1], z=tip[2])]
                marker.scale.x, marker.scale.y, marker.scale.z = 0.006, 0.015, 0.02
                markers.append(marker)
        arrow = self._marker(10, Marker.ARROW, origins[0], (0.12, 0.55, 0.52, 1.0))
        if imu is None:
            arrow.action = Marker.DELETE
        else:
            arrow.points = [Point(), Point(x=imu[0] * 0.025, y=imu[1] * 0.025, z=imu[2] * 0.025)]
            arrow.scale.x, arrow.scale.y, arrow.scale.z = 0.013, 0.035, 0.06
        markers.append(arrow)
        imu_text = "IMU:disconnected" if not board else "IMU:waiting"
        if imu:
            imu_text = (
                f"Acceleration:{math.hypot(*imu[:3]):.2f}m/s^2\n"
                f"Gyro:{math.hypot(*imu[3:]):.3f}rad/s"
            )
        markers.append(self._label(11, (-0.30, 0.0, 0.58), imu_text, imu is not None))
        cone = self._marker(20, Marker.TRIANGLE_LIST, origins[1], (0.17, 0.48, 0.65, 0.30))
        if distance is None:
            cone.action = Marker.DELETE
        else:
            length, fov = distance
            if fov == 0:
                cone.type = Marker.ARROW
                cone.color.a = 1.0
                cone.scale.x, cone.scale.y, cone.scale.z = 0.008, 0.025, 0.04
                cone.points = [Point(), Point(x=length)]
            else:
                radius = length * math.tan(fov / 2)
                for index in range(32):
                    angles = (index * math.tau / 32, (index + 1) * math.tau / 32)
                    points = [
                        Point(x=length, y=radius * math.cos(a), z=radius * math.sin(a))
                        for a in angles
                    ]
                    cone.points.extend([Point(), *points, Point(x=length), *reversed(points)])
        markers.append(cone)
        range_text = "Range:disconnected" if not board else "Range:unavailable"
        if distance:
            range_text = f"Distance:{distance[0] * 100:.1f}cm"
            if distance[1] == 0:
                range_text += "\nFoV:unspecified"
        markers.append(self._label(21, (0.30, 0.0, 0.58), range_text, distance is not None))
        return MarkerArray(markers=markers)

    def _tick(self):
        self.publisher.publish(self.markers())


def main(args=None):
    rclpy.init(args=args)
    node = SensorView()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
