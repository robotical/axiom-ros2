"""A teaching dashboard that observes ROS topics and stages local experiments."""

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
from std_msgs.msg import Float64, String, UInt64

from .experiment import Experiments


class TeachingNode(Node):
    """Keep visualization independent from the detector and robot-face processes."""

    def __init__(self):
        super().__init__('teaching_dashboard')
        defaults = {
            'imu_topic': '/axiom/bus_1/device_76a/imu/data_raw',
            'dashboard_host': '127.0.0.1',
            'dashboard_port': 8080,
            'recordings_dir': str(Path.home() / 'axiom-recordings'),
            'with_driver': True,
            'transport': 'ws',
            'device_uri': 'ws://host.docker.internal:8765/ws',
            'serial_port': '/dev/ttyACM0',
        }
        for name, default in defaults.items():
            self.declare_parameter(name, default, ParameterDescriptor(read_only=True))
        p = {name: self.get_parameter(name).value for name in defaults}
        self.topic = p['imu_topic']
        self.state_lock = threading.Lock()
        self.reset_view()
        self.graph = {'nodes': [], 'imu_subscribers': [], 'event_subscribers': []}
        sensor_qos = QoSProfile(depth=256, reliability=ReliabilityPolicy.BEST_EFFORT)
        latched = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.subscriptions_owned = [
            self.create_subscription(Imu, self.topic, self.on_imu, sensor_qos),
            self.create_subscription(Float64, '/axiom/shake/motion', self.on_motion, sensor_qos),
            self.create_subscription(ShakeEvent, '/axiom/shake/events', self.on_event, 10),
            self.create_subscription(UInt64, '/axiom/shake/count', self.on_count, latched),
            self.create_subscription(UInt64, '/axiom/strict/count', self.on_strict_count, latched),
            self.create_subscription(String, '/axiom/face/state', self.on_face, latched),
        ]
        driver_args = [
            '--ros-args',
            '-r',
            '__ns:=/axiom',
            '-p',
            'auto_connect:=true',
            '-p',
            'autosub:=true',
            '-p',
            'auto_reconnect:=true',
            '-p',
            'sensor_qos.depth:=256',
            '-p',
            f'transport:={p["transport"]}',
            '-p',
            f'device_uri:={p["device_uri"]}',
            '-p',
            f'serial.port:={p["serial_port"]}',
        ]
        self.experiments = Experiments(
            p['recordings_dir'], self.topic, driver_args, self.reset_view, live=p['with_driver']
        )
        self.timer = self.create_timer(0.5, self.refresh_graph)
        self.http_server = self.http_thread = None
        try:
            self.start_http(p['dashboard_host'], p['dashboard_port'])
        except Exception:
            self.experiments.close()
            raise

    def reset_view(self):
        with self.state_lock:
            self.points, self.events = deque(maxlen=600), deque(maxlen=30)
            self.samples = self.count = self.strict_count = 0
            self.motion = 0.0
            self.last_imu = self.last_face = self.last_point = None
            self.face_state = {'expression': 'curious', 'reactions': 0, 'event_id': None}

    def on_imu(self, msg):
        a, g = msg.linear_acceleration, msg.angular_velocity
        values = (a.x, a.y, a.z, g.x, g.y, g.z)
        now = time.monotonic()
        with self.state_lock:
            self.samples += 1
            self.last_imu = now
            if self.last_point is None or now - self.last_point >= 0.03:
                self.points.append(
                    [now, *[v if math.isfinite(v) else None for v in values], self.motion]
                )
                self.last_point = now
        self.experiments.last_imu = now

    def on_motion(self, msg):
        if math.isfinite(msg.data):
            with self.state_lock:
                self.motion = msg.data

    def on_event(self, msg):
        with self.state_lock:
            self.events.append(
                {
                    'id': msg.event_id,
                    'stamp': msg.header.stamp.sec + msg.header.stamp.nanosec / 1e9,
                    'motion': msg.motion_m_s2,
                    'pulses': msg.pulse_count,
                }
            )

    def on_count(self, msg):
        with self.state_lock:
            self.count = msg.data

    def on_strict_count(self, msg):
        with self.state_lock:
            self.strict_count = msg.data

    def on_face(self, msg):
        try:
            data = json.loads(msg.data)
            if data.get('expression') not in ('curious', 'happy', 'surprised', 'excited'):
                return
            with self.state_lock:
                self.face_state = data
                self.last_face = time.monotonic()
        except (ValueError, TypeError):
            pass

    def refresh_graph(self):
        def names(infos):
            return sorted({(i.node_namespace.rstrip('/') + '/' + i.node_name) for i in infos})

        graph = {
            'nodes': sorted(self.get_node_names()),
            'imu_subscribers': names(self.get_subscriptions_info_by_topic(self.topic)),
            'event_subscribers': names(
                self.get_subscriptions_info_by_topic('/axiom/shake/events')
            ),
        }
        with self.state_lock:
            self.graph = graph

    def snapshot(self):
        now = time.monotonic()
        with self.state_lock:
            result = {
                'topic': self.topic,
                'samples': self.samples,
                'count': self.count,
                'strict_count': self.strict_count,
                'motion': self.motion,
                'connected': self.last_imu is not None and now - self.last_imu < 2,
                'face_alive': self.last_face is not None and now - self.last_face < 2,
                'face': self.face_state,
                'points': list(self.points),
                'events': list(self.events),
                'graph': self.graph,
            }
        result['experiment'] = self.experiments.snapshot()
        return result

    def start_http(self, host, port):
        node = self
        page = Path(__file__).with_name('teaching.html').read_bytes()

        class Handler(BaseHTTPRequestHandler):
            def respond(self, status, value):
                data = (
                    value
                    if isinstance(value, bytes)
                    else json.dumps(value, allow_nan=False).encode()
                )
                self.send_response(status)
                self.send_header(
                    'Content-Type',
                    'text/html; charset=utf-8' if isinstance(value, bytes) else 'application/json',
                )
                self.send_header('Content-Length', str(len(data)))
                self.send_header('Cache-Control', 'no-store')
                self.end_headers()
                try:
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                if self.path == '/':
                    self.respond(200, page)
                elif self.path == '/api/state':
                    self.respond(200, node.snapshot())
                else:
                    self.respond(404, {'error': 'Not found'})

            def do_POST(self):
                # Only same-origin JSON requests can operate the local teaching controls.
                origin = self.headers.get('Origin')
                if (
                    self.path != '/api/action'
                    or self.headers.get('X-Axiom-Lab') != 'teaching'
                    or self.headers.get_content_type() != 'application/json'
                    or (
                        origin
                        and origin
                        not in (
                            'http://' + self.headers.get('Host', ''),
                            'https://' + self.headers.get('Host', ''),
                        )
                    )
                ):
                    self.respond(403, {'error': 'Use the local teaching controls'})
                    return
                try:
                    size = int(self.headers.get('Content-Length', 0))
                    if not 0 < size <= 4096:
                        raise ValueError('Invalid request size')
                    data = json.loads(self.rfile.read(size))
                    if not isinstance(data, dict):
                        raise ValueError('Expected an action object')
                    node.experiments.submit(data.get('action'), data)
                    self.respond(202, {'accepted': True})
                except (ValueError, TypeError) as exc:
                    self.respond(400, {'error': str(exc)})

            def log_message(self, *args):
                pass

        self.http_server = ThreadingHTTPServer((host, port), Handler)
        self.http_thread = threading.Thread(target=self.http_server.serve_forever, daemon=True)
        self.http_thread.start()
        self.get_logger().info(f'ROS teaching demo: http://{host}:{port}')

    def destroy_node(self):
        if self.http_server:
            self.http_server.shutdown()
            self.http_server.server_close()
            self.http_thread.join(timeout=2)
        self.experiments.close()
        return super().destroy_node()


def main(args=None):
    """Run the teaching platform and close its child processes on shutdown."""
    rclpy.init(args=args)
    node = None
    try:
        node = TeachingNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        if node:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
