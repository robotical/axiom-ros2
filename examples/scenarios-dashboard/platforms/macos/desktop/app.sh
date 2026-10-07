#!/usr/bin/env bash
# Native applications in the optional Linux desktop.
set -eo pipefail
source /opt/ros/jazzy/setup.bash
source /ws/install/setup.bash
cd /ws
case "${1:-}" in
  rviz)
    exec rviz2 -d /tmp/axiom-desktop.rviz
    ;;
  terminal)
    # X resources must match the custom class used by the desktop window rules.
    terminal_options=()
    terminal_title='ROS terminal'
    if [[ ${2:-} =~ ^[1-4]$ ]]; then
      terminal_options=(-name "axiom-terminal-$2")
      terminal_title="ROS terminal $2"
    fi
    terminal_command=(bash --rcfile /demo/platforms/macos/desktop/bashrc -i)
    if [[ ${2:-} == tmux ]]; then
      terminal_command=(bash /demo/scripts/ros_tmux.sh)
      terminal_title='ROS consoles'
    fi
    exec xterm -class AxiomTerminal "${terminal_options[@]}" -title "$terminal_title" \
      -xrm 'AxiomTerminal*selectToClipboard: true' \
      -xrm 'AxiomTerminal*VT100.translations: #override \n Ctrl Shift <Key>V: insert-selection(CLIPBOARD) \n Ctrl Shift <Key>C: copy-selection(CLIPBOARD) \n Shift <Key>Insert: insert-selection(CLIPBOARD)' \
      -fa 'DejaVu Sans Mono' -fs 10 -bg '#18232b' -fg '#e5eaed' \
      -e "${terminal_command[@]}"
    ;;
  dashboard)
    desktop_url=$(cat /tmp/axiom-dashboard-url)
    # Firefox runs as the image's unprivileged user, with its default sandbox.
    exec runuser -u ubuntu -- env XDG_RUNTIME_DIR=/tmp/runtime-ubuntu \
      dbus-run-session -- firefox-esr --profile /home/ubuntu/.axiom-dashboard \
      --class AxiomDashboard --new-window "$desktop_url"
    ;;
  *) exit 2 ;;
esac
