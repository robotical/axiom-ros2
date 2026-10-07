#!/usr/bin/env bash
set -euo pipefail
demo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
axiom_root=${AXIOM_ROS_ROOT:-"$(cd "$demo_root/../.." && pwd)"}
source_mounts=(-v "$axiom_root:/axiom:ro")
if [[ -n ${MARTY_ROS_ROOT:-} ]]; then
  source_mounts+=(-v "$MARTY_ROS_ROOT:/marty:ro")
fi
mkdir -p "$demo_root/.validation"
docker run --rm -e ROS_DOMAIN_ID=82 -e ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
  "${source_mounts[@]}" -v "$demo_root/src:/demo/src:ro" \
  -v "$demo_root/scripts:/demo/scripts:ro" -v "$demo_root/pyproject.toml:/demo/pyproject.toml:ro" \
  -v "$demo_root/.validation:/results" axiom-marty-demo-core:jazzy bash -lc '
    set -eo pipefail
    bash /demo/scripts/build_workspace.sh axiom_marty_dashboard
    source /opt/ros/jazzy/setup.bash
    source /ws/install/setup.bash
    pytest -q -p no:cacheprovider /demo/src/axiom_marty_dashboard/test --junitxml=/results/dashboard-pytest.xml
  ' > "$demo_root/.validation/dashboard-tests.log" 2>&1
