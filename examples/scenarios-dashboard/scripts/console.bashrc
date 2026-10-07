# Source the workspace, then leave the console ready for manual commands.
demo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
repo_root=${AXIOM_ROS_ROOT:-$(cd "$demo_root/../.." && pwd)}
source "$repo_root/scripts/setup_env.sh" || return
export HISTFILE=/dev/null
export PS1='\[\e[38;5;109m\]ROS '${ROS_PANE:-}'\[\e[0m\] \w $ '
