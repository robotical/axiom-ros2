# Source the workspace, then leave the console ready for manual commands.
script_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repo_root=${AXIOM_ROS_ROOT:-$(cd "$script_dir/.." && pwd)}
source "$repo_root/scripts/setup_env.sh" || return
export HISTFILE=/dev/null
export PS1='\[\e[38;5;109m\]ROS '${ROS_PANE:-}'\[\e[0m\] \w $ '
