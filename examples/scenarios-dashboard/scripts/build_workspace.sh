#!/usr/bin/env bash
set -eo pipefail
source /opt/ros/jazzy/setup.bash
paths=(/axiom/src /demo/src)
if [[ -d /marty/src ]]; then
  paths+=(/marty/src)
fi
colcon build --base-paths "${paths[@]}" --packages-up-to axiom_marty_demo "$@"
