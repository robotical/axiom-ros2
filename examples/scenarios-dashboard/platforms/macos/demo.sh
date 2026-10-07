#!/usr/bin/env bash
set -euo pipefail
demo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)
if [[ $(uname -s) != Darwin ]]; then
  echo 'For Linux, use: ros2 launch axiom_marty_demo workstation.launch.py' >&2
  exit 1
fi
if [[ ! -x "$demo_root/.venv/bin/python" ]]; then
  "${DEMO_PYTHON:-/opt/homebrew/bin/python3.12}" -m venv "$demo_root/.venv"
  "$demo_root/.venv/bin/python" -m pip install 'pyserial==3.5' 'websockets==15.0.1'
fi
exec "$demo_root/.venv/bin/python" "$demo_root/platforms/macos/demo.py" "$@"
