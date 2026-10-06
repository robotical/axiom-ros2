"""An independent application that reacts only to ROS ShakeEvent messages."""

import json

from axiom_interfaces.msg import ShakeEvent
import rclpy
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile
from std_msgs.msg import String


class RobotFace(Node):
    """Cycle expressions without importing the sensor driver or shake algorithm."""

    expressions = ('curious', 'happy', 'surprised', 'excited')

    def __init__(self):
        super().__init__('robot_face')
        self.hits = 0
        self.last_event = None
        self.expression = 'curious'
        self.publisher = self.create_publisher(
            String, 'face/state', QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        )
        self.subscription = self.create_subscription(ShakeEvent, 'shake/events', self.react, 10)
        self.timer = self.create_timer(0.5, self.publish_state)
        self.publish_state()

    def react(self, event):
        """Change expression when an actual event arrives through DDS."""
        self.hits += 1
        self.last_event = event.event_id
        self.expression = self.expressions[self.hits % len(self.expressions)]
        self.publish_state()

    def publish_state(self):
        """Publish presentation state and a heartbeat for the teaching dashboard."""
        self.publisher.publish(
            String(
                data=json.dumps(
                    {
                        'expression': self.expression,
                        'reactions': self.hits,
                        'event_id': self.last_event,
                    }
                )
            )
        )


def main(args=None):
    """Run the face as its own ROS process."""
    rclpy.init(args=args)
    node = RobotFace()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
