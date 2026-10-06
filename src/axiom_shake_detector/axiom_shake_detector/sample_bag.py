"""A labelled synthetic recording for lessons without a connected board."""

import math

from rclpy.serialization import serialize_message
import rosbag2_py
from sensor_msgs.msg import Imu


def make_sample(path, topic):
    """Save six seconds with two gestures; keep source timestamps repeatable."""
    writer = rosbag2_py.SequentialWriter()
    writer.open(
        rosbag2_py.StorageOptions(uri=str(path), storage_id='mcap'),
        rosbag2_py.ConverterOptions('', ''),
    )
    writer.create_topic(
        rosbag2_py.TopicMetadata(
            id=0, name=topic, type='sensor_msgs/msg/Imu', serialization_format='cdr'
        )
    )
    for i in range(600):
        msg = Imu()
        msg.header.stamp.sec = 100 + i // 100
        msg.header.stamp.nanosec = (i % 100) * 10_000_000
        msg.header.frame_id = 'synthetic_imu'
        msg.orientation_covariance[0] = -1.0
        msg.linear_acceleration.z = 9.81
        t = i / 100
        if 1 < t < 2 or 4 < t < 5:
            msg.linear_acceleration.x = 7 * math.sin(2 * math.pi * 4 * t)
        writer.write(topic, serialize_message(msg), 100_000_000_000 + i * 10_000_000)
    del writer
