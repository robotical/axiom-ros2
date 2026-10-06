#!/usr/bin/env python3
"""Write a clearly synthetic, repeatable IMU-only MCAP experiment inside ROS."""

import argparse
import math

from rclpy.serialization import serialize_message
import rosbag2_py
from sensor_msgs.msg import Imu

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('output', help='New bag directory (must not already exist)')
parser.add_argument('--topic', default='/axiom/bus_1/device_76a/imu/data_raw')
args = parser.parse_args()
writer = rosbag2_py.SequentialWriter()
writer.open(
    rosbag2_py.StorageOptions(uri=args.output, storage_id='mcap'),
    rosbag2_py.ConverterOptions('', ''),
)
writer.create_topic(
    rosbag2_py.TopicMetadata(
        id=0, name=args.topic, type='sensor_msgs/msg/Imu', serialization_format='cdr'
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
    # Two separated gestures, with stationary time to settle the filter.
    if 1 < t < 2 or 4 < t < 5:
        msg.linear_acceleration.x = 7 * math.sin(2 * math.pi * 4 * t)
    stamp_ns = msg.header.stamp.sec * 1_000_000_000 + msg.header.stamp.nanosec
    writer.write(args.topic, serialize_message(msg), stamp_ns)
del writer
print(f'Synthetic demo: {args.output}; 600 IMU samples, two shake gestures.')
