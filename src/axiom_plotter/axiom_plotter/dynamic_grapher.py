#!/usr/bin/env python3
import argparse
from collections import defaultdict
from functools import partial
import re
import threading
from typing import Any, Callable, Dict

import matplotlib.animation as animation

# ---- plotting (matplotlib) ----
import matplotlib.pyplot as plt
import rclpy
from rclpy.node import Node
from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
from rosidl_runtime_py.utilities import get_message

from .history import TimeWindow

NUMERIC_STD_TYPES = {
    'std_msgs/msg/Float32': ('data', float),
    'std_msgs/msg/Float64': ('data', float),
    'std_msgs/msg/Int32': ('data', float),
    'std_msgs/msg/Int64': ('data', float),
    'std_msgs/msg/UInt32': ('data', float),
    'std_msgs/msg/UInt64': ('data', float),
}
# add common single-field numeric messages here
EXTRA_TYPES = {
    'sensor_msgs/msg/Range': ('range', float),
}


def resolve_attr_path(msg, path: str):
    """Traverse dot path like 'pose.position.z'."""
    cur = msg
    for p in path.split('.'):
        cur = getattr(cur, p)
    return cur


def extract_field(message, field, caster):
    return caster(getattr(message, field))


def extract_path(message, path):
    return float(resolve_attr_path(message, path))


class DynamicGrapher(Node):
    def __init__(self, args):
        super().__init__('dynamic_grapher')
        self.args = args

        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT
            if args.sensor_qos
            else ReliabilityPolicy.RELIABLE,
            history=HistoryPolicy.KEEP_LAST,
            depth=args.qos_depth,
        )
        self.qos = qos

        # topic -> deque[(t, y)]
        self.buffers = defaultdict(lambda: TimeWindow(args.history_sec, args.max_points))
        self.topic_filter = re.compile(args.topic_regex)
        self.lock = threading.Lock()
        self.subscriptions_map: Dict[str, Any] = {}
        self.extractors: Dict[str, Callable[[Any], float]] = {}

        # discovery thread
        self._stop = threading.Event()
        self.disc_thread = threading.Thread(target=self.discovery_loop, daemon=True)
        self.disc_thread.start()

        # plotting setup
        self.fig, self.ax = plt.subplots()
        self.lines: Dict[str, Any] = {}
        self.ax.set_title('Dynamic ROS 2 Live Plot')
        self.ax.set_xlabel('Time (s, relative)')
        self.ax.set_ylabel('Value')
        self.anim = animation.FuncAnimation(
            self.fig, self._animate, interval=1000.0 / args.rate_hz
        )

    # ---- discovery ----
    def discovery_loop(self):
        while not self._stop.is_set():
            try:
                topics_and_types = self.get_topic_names_and_types()
                for topic, types in topics_and_types:
                    # Only 1 type expected per topic; skip multi-type edge cases
                    if not types:
                        continue
                    msg_type = types[0]

                    if topic in self.subscriptions_map:
                        continue  # already subscribed

                    if not self.topic_filter.search(topic):
                        continue

                    # 1) Known numeric std types
                    if msg_type in NUMERIC_STD_TYPES:
                        field, caster = NUMERIC_STD_TYPES[msg_type]

                        extractor = partial(extract_field, field=field, caster=caster)
                    # 2) Extras we whitelisted
                    elif msg_type in EXTRA_TYPES:
                        field, caster = EXTRA_TYPES[msg_type]

                        extractor = partial(extract_field, field=field, caster=caster)
                    # 3) User-specified field path (works for any message)
                    elif self.args.field:
                        # Verify field exists by creating a dummy instance if possible
                        extractor = partial(extract_path, path=self.args.field)
                    else:
                        continue

                    if extractor:
                        try:
                            pkg, _, name = msg_type.partition('/msg/')
                            mod = get_message(msg_type)  # returns the class
                            sub = self.create_subscription(
                                mod, topic, self._make_cb(topic, extractor), self.qos
                            )
                            self.subscriptions_map[topic] = sub
                            self.extractors[topic] = extractor
                            self.get_logger().info(f'Subscribed: {topic} [{msg_type}]')
                        except Exception as e:
                            self.get_logger().warn(
                                f'Failed to subscribe {topic} [{msg_type}]: {e}'
                            )
                self._stop.wait(self.args.discovery_interval)
            except Exception as e:
                self.get_logger().warn(f'Discovery error: {e}')
                self._stop.wait(2.0)

    def _make_cb(self, topic: str, extractor: Callable[[Any], float]):
        def _cb(msg):
            try:
                y = extractor(msg)
                t = self.get_clock().now().nanoseconds * 1e-9
                with self.lock:
                    if hasattr(msg, 'header'):
                        t = msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9
                    self.buffers[topic].append(t, y)
            except Exception as e:
                self.get_logger().warn(f'Extraction failed for {topic}: {e}')

        return _cb

    # ---- plotting ----
    def _animate(self, frame):
        # establish relative time
        now = self.get_clock().now().nanoseconds * 1e-9
        with self.lock:
            topics = list(self.buffers.keys())
            for topic in topics:
                buf = self.buffers[topic].prune(now)
                if not buf:
                    continue
                ts, ys = zip(*buf)
                t0 = now - self.args.history_sec
                xs = [t - t0 for t in ts]  # shift to [0, history]
                if topic not in self.lines:
                    (self.lines[topic],) = self.ax.plot(xs, ys, label=topic)
                    self.ax.legend(loc='upper left', fontsize='small')
                else:
                    self.lines[topic].set_data(xs, ys)

            # update axes range
            self.ax.relim()
            self.ax.autoscale_view()

        return list(self.lines.values())

    def stop(self):
        self._stop.set()
        self.disc_thread.join(timeout=3)


def main():
    parser = argparse.ArgumentParser(description='Dynamic ROS 2 grapher')
    parser.add_argument(
        '--topic-regex',
        default='',
        help="Regular expression to filter topics (e.g. '/imu/data_raw$')",
    )
    parser.add_argument(
        '--field',
        default='',
        help="Dot path to a numeric field for non-std messages, e.g. 'pose.position.z'",
    )
    parser.add_argument('--discovery-interval', type=float, default=2.0)
    parser.add_argument('--history-sec', type=float, default=60.0)
    parser.add_argument('--rate-hz', type=float, default=10.0)
    parser.add_argument(
        '--sensor-qos', action='store_true', help='Use BEST_EFFORT for sensor topics'
    )
    parser.add_argument('--qos-depth', type=int, default=50)
    parser.add_argument(
        '--max-points',
        type=int,
        default=100000,
        help='Memory limit per topic, independent of GUI refresh rate',
    )
    args, unknown = parser.parse_known_args()

    if (
        min(
            args.discovery_interval,
            args.history_sec,
            args.rate_hz,
            args.qos_depth,
            args.max_points,
        )
        <= 0
    ):
        parser.error('Intervals, rates and capacities must be positive')
    rclpy.init(args=unknown)
    node = DynamicGrapher(args)
    try:
        # Run ROS executor in a background thread so matplotlib owns the main thread.
        executor = rclpy.executors.MultiThreadedExecutor()
        executor.add_node(node)
        spin_thread = threading.Thread(target=executor.spin, daemon=True)
        spin_thread.start()

        plt.show()  # blocks; animation pulls from node.buffers
    finally:
        node.stop()
        executor.shutdown()
        spin_thread.join(timeout=3)
        node.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == '__main__':
    main()
