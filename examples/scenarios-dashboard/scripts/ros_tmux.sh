#!/usr/bin/env bash
# Compatibility for published guides; the shared helper lives in repository scripts/.
repo_root=${AXIOM_ROS_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)} || exit
exec bash "$repo_root/scripts/ros_tmux.sh" "$@"
