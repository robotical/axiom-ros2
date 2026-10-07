#!/usr/bin/env python3
"""Record real inventory changes, publisher counts and range data without controlling Axiom."""

import argparse
import json
import math
from pathlib import Path
import time

import rclpy
from rclpy.qos import DurabilityPolicy, QoSProfile, qos_profile_sensor_data
from sensor_msgs.msg import Range
from std_msgs.msg import String


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--namespace", default="/axiom")
    parser.add_argument("--duration", type=float, default=120)
    parser.add_argument("--output", default="/ws/hotplug-validation.json")
    args = parser.parse_args()
    rclpy.init()
    node = rclpy.create_node("hotplug_validation")
    root = "/" + args.namespace.strip("/")
    events, readings = [], []
    previous = None

    def inventory(msg):
        nonlocal previous
        rows = json.loads(msg.data)
        state = [
            {k: d.get(k) for k in ("topic", "type", "online", "stale", "aliases")} for d in rows
        ]
        signature = json.dumps(state, sort_keys=True)
        if signature != previous:
            events.append(dict(time=time.time(), devices=state))
            print(json.dumps(events[-1]), flush=True)
            previous = signature

    def distance(msg):
        if math.isfinite(msg.range):
            readings.append(dict(time=time.time(), metres=msg.range))

    node.create_subscription(
        String,
        root + "/devices",
        inventory,
        QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL),
    )
    node.create_subscription(Range, root + "/range", distance, qos_profile_sensor_data)
    deadline = time.monotonic() + args.duration
    counts, previous_count = [], None
    try:
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            count = node.count_publishers(root + "/range")
            if count != previous_count:
                counts.append(dict(time=time.time(), publishers=count))
                print(json.dumps(counts[-1]), flush=True)
                previous_count = count
            Path(args.output).write_text(
                json.dumps(
                    dict(events=events, publishers=counts, finite_readings=readings), indent=2
                )
            )
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
