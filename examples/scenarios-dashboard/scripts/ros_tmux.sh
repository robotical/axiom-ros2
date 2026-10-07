#!/usr/bin/env bash
# Four empty ROS consoles. No drivers, connections or acquisition are started.
set -euo pipefail
demo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
export ROS_WORKSPACE=${ROS_WORKSPACE:-$PWD}
session=axiom
tmux_cmd=(tmux -L axiom-ros -f "$demo_root/scripts/tmux.conf")
if ! "${tmux_cmd[@]}" has-session -t "$session" 2>/dev/null; then
  for pane in 1 2 3 4; do
    printf -v shell_command 'env ROS_PANE=%q bash --rcfile %q -i' "$pane" "$demo_root/scripts/console.bashrc"
    if [[ $pane == 1 ]]; then
      "${tmux_cmd[@]}" new-session -d -s "$session" -n ROS -c "$ROS_WORKSPACE" "$shell_command"
    else
      "${tmux_cmd[@]}" split-window -t "$session" -c "$ROS_WORKSPACE" "$shell_command"
      "${tmux_cmd[@]}" select-layout -t "$session" tiled >/dev/null
    fi
  done
  "${tmux_cmd[@]}" select-pane -t "$session:0.1"
fi
if [[ ${1:-} != --prepare ]]; then
  exec "${tmux_cmd[@]}" attach-session -t "$session"
fi
