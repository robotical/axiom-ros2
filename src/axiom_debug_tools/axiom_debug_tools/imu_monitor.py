import math
import time
import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, QoSReliabilityPolicy
from sensor_msgs.msg import Imu

class ImuMonitor(Node):
    def __init__(self):
        super().__init__('axiom_imu_monitor')
        self.declare_parameter('topic', '/imu/data_raw')
        topic = self.get_parameter('topic').get_parameter_value().string_value
        qos = QoSProfile(depth=50, reliability=QoSReliabilityPolicy.BEST_EFFORT)
        self._last = None
        self._n = 0
        self._gx = self._gy = self._gz = 0.0
        self.create_subscription(Imu, topic, self._cb, qos)
        self.get_logger().info(f"IMU monitor listening on {topic}")

    def _cb(self, m: Imu):
        now = time.time()
        if self._last is not None:
            dt = now - self._last
            hz = 1.0 / dt if dt > 0 else float('inf')
        else:
            hz = float('nan')
        self._last = now
        self._n += 1
        ax, ay, az = m.linear_acceleration.x, m.linear_acceleration.y, m.linear_acceleration.z
        gx, gy, gz = m.angular_velocity.x, m.angular_velocity.y, m.angular_velocity.z
        anorm = math.sqrt(ax*ax + ay*ay + az*az)
        self._gx += gx; self._gy += gy; self._gz += gz
        bx, by, bz = self._gx/self._n, self._gy/self._n, self._gz/self._n
        warn = []
        if not (5.0 < anorm < 15.0):  # crude 1g check in m/s^2
            warn.append(f"acc_norm={anorm:.2f}")
        if any(math.isnan(v) for v in (ax,ay,az,gx,gy,gz)):
            warn.append("NaN detected")
        self.get_logger().info(
            f"[{self._n}] ~{hz:.2f}Hz | acc=({ax:.2f},{ay:.2f},{az:.2f}) | gyro=({gx:.2f},{gy:.2f},{gz:.2f}) | bias≈({bx:.3f},{by:.3f},{bz:.3f}) "
            + ("⚠ " + ", ".join(warn) if warn else "")
        )

def main(args=None):
    rclpy.init(args=args)
    try:
        node = ImuMonitor()
        rclpy.spin(node)
    finally:
        rclpy.shutdown()