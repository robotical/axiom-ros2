#!/usr/bin/env bash
set -euo pipefail
demo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
axiom_root=${AXIOM_ROS_ROOT:-"$(cd "$demo_root/../.." && pwd)"}
source_mounts=(-v "$axiom_root:/axiom:ro")
if [[ -n ${MARTY_ROS_ROOT:-} ]]; then
  source_mounts+=(-v "$MARTY_ROS_ROOT:/marty:ro")
fi
mkdir -p "$demo_root/.validation"
docker build -t axiom-marty-demo-core:jazzy -f "$demo_root/scripts/Dockerfile" "$demo_root/scripts"
docker run --rm -e ROS_DOMAIN_ID=81 -e ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST -e MARTY_ROS_TEST_ROOT=/marty \
  "${source_mounts[@]}" \
  -v "$demo_root/src/axiom_marty_demo:/demo/src/axiom_marty_demo:ro" -v "$demo_root/scripts:/demo/scripts:ro" \
  -v "$demo_root/pyproject.toml:/demo/pyproject.toml:ro" \
  -v "$demo_root/.validation:/results" \
  axiom-marty-demo-core:jazzy bash -lc '
    set -eo pipefail
    bash /demo/scripts/build_workspace.sh
    source /opt/ros/jazzy/setup.bash
    source /ws/install/setup.bash
    pytest -q -p no:cacheprovider /demo/src/axiom_marty_demo/test --junitxml=/results/pytest.xml
    ros2 launch axiom_marty_demo workstation.launch.py --show-args
    bash /demo/scripts/ros_tmux.sh --prepare
    test "$(tmux -L axiom-ros list-panes | wc -l)" -eq 4
    tmux -L axiom-ros kill-server
  ' 2>&1 | tee "$demo_root/.validation/ros.log"
