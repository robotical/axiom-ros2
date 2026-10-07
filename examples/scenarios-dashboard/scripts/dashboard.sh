#!/usr/bin/env bash
# Load the same machine configuration as the ROS consoles, then start the guide.
set -eo pipefail
demo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
repo_root=${AXIOM_ROS_ROOT:-$(cd "$demo_root/../.." && pwd)}
source "$repo_root/scripts/setup_env.sh"
exec ros2 run axiom_marty_dashboard dashboard "$@"
