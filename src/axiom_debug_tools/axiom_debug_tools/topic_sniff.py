import time
import json
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy, QoSHistoryPolicy
from rosidl_runtime_py.utilities import get_message
from rosidl_runtime_py.convert import message_to_ordereddict

class TopicSniff(Node):
    def __init__(self):
        super().__init__('axiom_topic_sniff')
        self.declare_parameter('topic', '')
        self.declare_parameter('type', '')  # e.g. sensor_msgs/msg/Imu
        self.declare_parameter('depth', 10)
        topic = self.get_parameter('topic').get_parameter_value().string_value
        type_str = self.get_parameter('type').get_parameter_value().string_value
        depth = self.get_parameter('depth').get_parameter_value().integer_value
        if not topic or not type_str:
            raise RuntimeError("Parameters 'topic' and 'type' are required")
        msg_type = get_message(type_str)
        qos = QoSProfile(depth=depth)
        qos.reliability = QoSReliabilityPolicy.BEST_EFFORT
        qos.history = QoSHistoryPolicy.KEEP_LAST
        self._last_time = None
        self._count = 0
        self._topic = topic
        self.create_subscription(msg_type, topic, self._cb, qos)
        self.get_logger().info(f"Sniffing {topic} [{type_str}]…")

    def _cb(self, msg):
        now = time.time()
        if self._last_time is not None:
            dt = now - self._last_time
            hz = 1.0 / dt if dt > 0 else float('inf')
        else:
            hz = float('nan')
        self._last_time = now
        self._count += 1
        pretty = json.dumps(message_to_ordereddict(msg), ensure_ascii=False)
        self.get_logger().info(f"[{self._count}] {self._topic} @ ~{hz:.2f} Hz {pretty}")

def main(args=None):
    rclpy.init(args=args)
    try:
        node = TopicSniff()
        rclpy.spin(node)
    finally:
        rclpy.shutdown()