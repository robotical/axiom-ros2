#!/usr/bin/env bash
# Clean Linux ROS build: source mounted read-only, no hardware or host ROS needed.
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
image=${ROS_VALIDATION_IMAGE:-ros:jazzy-ros-base@sha256:c3706ef0a0aa45413c07803cf433602f543b22e45b4855f6fca955c2d8ecc4e8}
docker run --rm -v "$repo_root:/work:ro" -w /ws "$image" bash -lc '
  set -eo pipefail
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq python3-serial python3-websocket python3-websockets \
    python3-pytest python3-matplotlib python3-numpy \
    ros-jazzy-diagnostic-msgs ros-jazzy-ament-lint-common ros-jazzy-ament-lint-auto \
    ros-jazzy-rosbag2-storage-mcap
  source /opt/ros/jazzy/setup.bash
  export PYTHONDONTWRITEBYTECODE=1
  colcon build --base-paths /work/src
  source /ws/install/setup.bash
  colcon test --base-paths /work/src --event-handlers console_direct+ --return-code-on-test-failure
  colcon test-result --verbose
  ros2 launch axiom_bringup bringup.launch.py --show-args
'
