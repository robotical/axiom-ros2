"""ROS IMU subscriber, shake events and a small read-only movement dashboard."""

from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
from pathlib import Path
import threading
import time

from axiom_interfaces.msg import ShakeEvent
from rcl_interfaces.msg import ParameterDescriptor
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import Imu
from std_msgs.msg import Float64, UInt64

from .detector import ShakeDetector


class ShakeNode(Node):
    """Publish one event per detected gesture and expose recent data over HTTP."""

    def __init__(self):
        super().__init__('shake_detector')
        defaults = {
            'imu_topic': '/axiom/bus_1/device_76a/imu/data_raw',
            'threshold': 3.0,
            'release': 1.2,
            'window': 0.8,
            'min_pulses': 3,
            'cooldown': 1.5,
            'gravity_tau': 0.35,
            'warmup': 0.5,
            'max_gap': 0.5,
            'dashboard_host': '127.0.0.1',
            'dashboard_port': 8080,
        }
        for name, default in defaults.items():
            self.declare_parameter(name, default, ParameterDescriptor(read_only=True))
        params = {name: self.get_parameter(name).value for name in defaults}
        self.detector = ShakeDetector(
            **{
                k: v
                for k, v in params.items()
                if k not in ('imu_topic', 'dashboard_host', 'dashboard_port')
            }
        )
        self.imu_topic = params['imu_topic']
        self.event_pub = self.create_publisher(ShakeEvent, 'shake/events', 10)
        # Axiom's FIFO arrives in bursts, larger than the five-sample sensor preset.
        sensor_qos = QoSProfile(depth=256, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.motion_pub = self.create_publisher(Float64, 'shake/motion', sensor_qos)
        self.count_pub = self.create_publisher(
            UInt64, 'shake/count', QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        )
        self.count_pub.publish(UInt64(data=0))
        self.state_lock = threading.Lock()
        self.points, self.events = deque(maxlen=600), deque(maxlen=30)
        self.sample_count = self.event_count = self.invalid_count = 0
        self.last_received = None
        self.last_chart_stamp = None
        self.warming_up = True
        self.subscription = self.create_subscription(Imu, self.imu_topic, self.on_imu, sensor_qos)
        self.http_server = self.http_thread = None
        port = params['dashboard_port']
        if not 0 <= port <= 65535:
            raise ValueError('dashboard_port must be 0 (disabled) or 1..65535')
        if port:
            self.start_dashboard(params['dashboard_host'], port)
        self.get_logger().info(
            f'Listening for IMU on {self.imu_topic}; threshold={params["threshold"]}'
        )

    def on_imu(self, msg):
        """Use source timestamps so playback speed does not change detections."""
        stamp = msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9
        a = msg.linear_acceleration
        if msg.linear_acceleration_covariance[0] == -1:
            self.detector.reset()
            with self.state_lock:
                self.invalid_count += 1
            return
        reading = self.detector.update(stamp, (a.x, a.y, a.z))
        if reading is None:
            with self.state_lock:
                self.invalid_count += 1
            return
        self.motion_pub.publish(Float64(data=reading.motion))
        with self.state_lock:
            self.sample_count += 1
            self.last_received = time.monotonic()
            self.warming_up = not reading.ready
            if self.last_chart_stamp is not None and stamp < self.last_chart_stamp:
                self.points.clear()
                self.last_chart_stamp = None
            if self.last_chart_stamp is None or stamp - self.last_chart_stamp >= 0.03:
                angular = msg.angular_velocity
                gyro = [
                    v if math.isfinite(v) and msg.angular_velocity_covariance[0] != -1 else None
                    for v in (angular.x, angular.y, angular.z)
                ]
                self.points.append([stamp, a.x, a.y, a.z, reading.motion, *gyro])
                self.last_chart_stamp = stamp
            if reading.triggered:
                self.event_count += 1
                self.events.append(
                    {'stamp': stamp, 'id': self.event_count, 'motion': reading.motion}
                )
                event = ShakeEvent(
                    header=msg.header,
                    event_id=self.event_count,
                    motion_m_s2=reading.motion,
                    pulse_count=reading.pulses,
                )
                self.event_pub.publish(event)
                self.count_pub.publish(UInt64(data=self.event_count))
                self.get_logger().info(
                    f'SHAKE #{self.event_count}: {reading.pulses} pulses, '
                    f'{reading.motion:.2f} m/s²'
                )

    def snapshot(self):
        """Return a bounded view for the browser without exposing hardware controls."""
        with self.state_lock:
            age = None if self.last_received is None else time.monotonic() - self.last_received
            return {
                'topic': self.imu_topic,
                'samples': self.sample_count,
                'count': self.event_count,
                'invalid': self.invalid_count,
                'age_s': age,
                'connected': age is not None and age < 2.0,
                'warming_up': self.warming_up,
                'threshold': self.detector.threshold,
                'points': list(self.points),
                'events': list(self.events),
            }

    def start_dashboard(self, host, port):
        """Serve the bundled page and JSON; no network resources are required."""
        node = self
        page = Path(__file__).with_name('dashboard.html').read_bytes()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path == '/':
                    body, mime = page, 'text/html; charset=utf-8'
                elif self.path == '/api/state':
                    body = json.dumps(node.snapshot(), allow_nan=False).encode()
                    mime = 'application/json'
                else:
                    self.send_error(404)
                    return
                self.send_response(200)
                self.send_header('Content-Type', mime)
                self.send_header('Content-Length', str(len(body)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                try:
                    self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.http_server = ThreadingHTTPServer((host, port), Handler)
        self.http_thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
        self.http_thread.start()
        self.get_logger().info(f'Movement dashboard: http://{host}:{port}')

    def destroy_node(self):
        """Release the HTTP listener as well as the ROS resources."""
        if self.http_server:
            self.http_server.shutdown()
            self.http_server.server_close()
            self.http_thread.join(timeout=2)
        return super().destroy_node()


def main(args=None):
    """Run the detector until interrupted."""
    rclpy.init(args=args)
    node = None
    try:
        node = ShakeNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        if node:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
