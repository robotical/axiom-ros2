import time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import Range

class RangeMonitor(Node):
    def __init__(self):
        super().__init__('axiom_range_monitor')
        self.declare_parameter('topic', '/range/front')
        topic = self.get_parameter('topic').get_parameter_value().string_value
        qos = QoSProfile(depth=20, reliability=QoSReliabilityPolicy.RELIABLE)
        self._last = None
        self._n = 0
        self.create_subscription(Range, topic, self._cb, qos)
        self.get_logger().info(f"Range monitor on {topic}")

    def _cb(self, m: Range):
        now = time.time()
        hz = float('nan') if self._last is None else (1.0 / (now - self._last) if now > self._last else float('inf'))
        self._last = now
        self._n += 1
        oor = m.range < m.min_range or m.range > m.max_range
        flag = "⚠ OOR" if oor else ""
        self.get_logger().info(f"[{self._n}] ~{hz:.2f}Hz | {m.range:.3f} m (min={m.min_range:.2f}, max={m.max_range:.2f}) {flag}")

def main(args=None):
    rclpy.init(args=args)
    try:
        node = RangeMonitor()
        rclpy.spin(node)
    finally:
        rclpy.shutdown()