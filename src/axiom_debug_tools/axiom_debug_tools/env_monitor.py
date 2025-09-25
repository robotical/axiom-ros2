import time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import Temperature, RelativeHumidity

class EnvMonitor(Node):
    def __init__(self):
        super().__init__('axiom_env_monitor')
        self.declare_parameter('temp_topic', '/environment/temperature')
        self.declare_parameter('hum_topic', '/environment/humidity')
        ttopic = self.get_parameter('temp_topic').get_parameter_value().string_value
        htopic = self.get_parameter('hum_topic').get_parameter_value().string_value
        qos = QoSProfile(depth=10, reliability=QoSReliabilityPolicy.RELIABLE)
        self._last_t = self._last_h = None
        self._n_t = self._n_h = 0
        self.create_subscription(Temperature, ttopic, self._cb_t, qos)
        self.create_subscription(RelativeHumidity, htopic, self._cb_h, qos)
        self.get_logger().info(f"Env monitor on {ttopic} & {htopic}")

    def _cb_t(self, m: Temperature):
        now = time.time()
        hz = float('nan') if self._last_t is None else (1.0 / (now - self._last_t) if now > self._last_t else float('inf'))
        self._last_t = now
        self._n_t += 1
        self.get_logger().info(f"[T {self._n_t}] ~{hz:.2f}Hz | {m.temperature:.2f} °C")

    def _cb_h(self, m: RelativeHumidity):
        now = time.time()
        hz = float('nan') if self._last_h is None else (1.0 / (now - self._last_h) if now > self._last_h else float('inf'))
        self._last_h = now
        self._n_h += 1
        self.get_logger().info(f"[H {self._n_h}] ~{hz:.2f}Hz | {m.relative_humidity*100.0:.1f} %RH")

def main(args=None):
    rclpy.init(args=args)
    try:
        node = EnvMonitor()
        rclpy.spin(node)
    finally:
        rclpy.shutdown()