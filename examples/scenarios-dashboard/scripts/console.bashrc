# Source the workspace, then leave the console ready for manual commands.
[[ ! -f /opt/ros/jazzy/setup.bash ]] || source /opt/ros/jazzy/setup.bash
[[ ! -f ${ROS_WORKSPACE:-$PWD}/install/setup.bash ]] || source "${ROS_WORKSPACE:-$PWD}/install/setup.bash"
export HISTFILE=/dev/null
export PS1='\[\e[38;5;109m\]ROS '${ROS_PANE:-}'\[\e[0m\] \w $ '
