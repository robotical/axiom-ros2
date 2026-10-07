"""Optional Linux desktop. ROS drivers and acquisition are always manual."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

from desktop_runtime import DesktopRuntime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--demo", choices=["learning"], default="learning")
    parser.add_argument("--marty-ip")
    parser.add_argument("--with-dashboard", action="store_true")
    args, options = parser.parse_known_args()
    boards = json.loads(os.environ.get("AXIOM_ROS_BOARDS", "{}"))
    if boards:
        for board in boards.values():
            board["topic_aliases"] = {
                "imu/data_raw": {"type": "LSM6DS", "source": "imu/data_raw"},
                "range": {"type": "VL53L4CD", "source": "range"},
            }
        Path("/ws/axioms.yaml").write_text(json.dumps({"axioms": boards}, indent=2))
    port = 8083 if args.with_dashboard else 0
    for option in options:
        if option.startswith("dashboard_port:="):
            port = int(option.split(":=", 1)[1])
    viewer = DesktopRuntime(port, auto_apps=False)
    child, stopped = None, 0

    def stop(sig, frame):
        nonlocal stopped
        stopped = sig
        if child and child.poll() is None:
            child.send_signal(sig)

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    try:
        viewer.start()
        if args.with_dashboard and not stopped:
            child = subprocess.Popen(
                [
                    "ros2",
                    "run",
                    "axiom_marty_dashboard",
                    "dashboard",
                    "--ros-args",
                    "-p",
                    "host:=0.0.0.0",
                    "-p",
                    f"port:={port}",
                    "-p",
                    "workstation_reset_dir:=/ws/.session-reset",
                ],
                start_new_session=True,
            )
        while not stopped:
            if child and child.poll() is not None:
                print("Guide stopped; the consoles remain available.", flush=True)
                child = None
            viewer.open_dashboard_when_ready()
            viewer.publish()
            time.sleep(0.5)
        return 128 + stopped
    finally:
        if child and child.poll() is None:
            child.send_signal(signal.SIGTERM)
            try:
                child.wait(10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        viewer.close()


if __name__ == "__main__":
    sys.exit(main())
