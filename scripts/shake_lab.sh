#!/usr/bin/env bash
# Local macOS/Docker movement lab. Runtime files stay outside tracked source.
set -euo pipefail
repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
state="$repo_root/.shake-lab"
container=axiom-shake-lab
image=axiom-shake-lab:jazzy
imu_topic=${AXIOM_IMU_TOPIC:-/axiom/bus_1/device_76a/imu/data_raw}
mkdir -p "$state/recordings"

owned_container() {
  test "$(docker inspect -f '{{index .Config.Labels "com.robotical.shake-lab"}}' "$container" 2>/dev/null || true)" = true
}
stop_lab() {
  if owned_container; then docker stop --signal SIGINT --time 15 "$container" >/dev/null; docker rm "$container" >/dev/null; fi
  if test -f "$state/relay.pid"; then
    relay_pid=$(cat "$state/relay.pid")
    case "$(ps -p "$relay_pid" -o command= 2>/dev/null || true)" in
      *"$repo_root/scripts/usb_ros_relay.py"*) kill "$relay_pid" 2>/dev/null || true ;;
    esac
    rm -f "$state/relay.pid"
  fi
}
start_lab() {
  mode=$1
  if docker inspect "$container" >/dev/null 2>&1; then
    echo 'A container named axiom-shake-lab already exists. Run stop first.' >&2; exit 1
  fi
  docker image inspect "$image" >/dev/null
  if test "$mode" = live; then
    port=${2:-}
    if test -z "$port"; then
      port=$("$state/venv/bin/python" -c 'from serial.tools.list_ports import comports; p=[p.device for p in comports() if p.vid==0x303a and p.pid==0x1001]; print(p[0] if len(p)==1 else "")')
    fi
    if test -z "$port"; then echo 'Specify the USB port: start /dev/cu.usbmodem…' >&2; exit 1; fi
    # A separate process session survives the invoking terminal's process group.
    "$state/venv/bin/python" - "$repo_root" "$port" <<'PY'
from pathlib import Path
import subprocess
import sys
root = Path(sys.argv[1])
state = root / '.shake-lab'
with (state / 'relay.log').open('w') as log:
    process = subprocess.Popen(
        [sys.executable, '-u', str(root / 'scripts/usb_ros_relay.py'), '--port', sys.argv[2]],
        stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True,
    )
(state / 'relay.pid').write_text(str(process.pid))
PY
    sleep 1
    if ! kill -0 "$(cat "$state/relay.pid")" 2>/dev/null; then cat "$state/relay.log"; exit 1; fi
    with_driver=true
  else
    with_driver=false
  fi
  if ! docker run -d --init --name "$container" --label com.robotical.shake-lab=true \
    -p 127.0.0.1:8080:8080 -v "$repo_root:/work:ro" \
    -v "$state/ws:/ws" -v "$state/recordings:/recordings" \
    -e ROS_DOMAIN_ID=42 -e ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST \
    -e WITH_DRIVER="$with_driver" -e IMU_TOPIC="$imu_topic" \
    "$image" bash -lc '
      set -eo pipefail
      source /opt/ros/jazzy/setup.bash
      colcon build --base-paths /work/src --packages-up-to axiom_shake_detector
      source /ws/install/setup.bash
      exec ros2 launch axiom_shake_detector shake_lab.launch.py \
        with_driver:="$WITH_DRIVER" imu_topic:="$IMU_TOPIC" dashboard_host:=0.0.0.0 recordings_dir:=/recordings
    ' > "$state/container.id"; then
    stop_lab; exit 1
  fi
  for attempt in $(seq 1 180); do
    if python3 - "$mode" <<'PY'
import json
import sys
from urllib.request import urlopen
try:
    with urlopen('http://127.0.0.1:8080/api/state', timeout=1) as response:
        state = json.load(response)
    sys.exit(0 if sys.argv[1] == 'replay' or state['connected'] else 1)
except Exception:
    sys.exit(1)
PY
    then
      echo "Movement lab ready: http://localhost:8080 ($mode)"; return
    fi
    if test "$(docker inspect -f '{{.State.Running}}' "$container")" != true; then
      docker logs "$container"; stop_lab; exit 1
    fi
    sleep 1
  done
  echo 'Startup timed out waiting for the dashboard and IMU. Startup log:' >&2
  docker logs --tail 30 "$container"
  stop_lab
  exit 1
}
ros_exec() {
  owned_container || { echo 'Start the movement lab first.' >&2; exit 1; }
  docker exec "$container" bash -lc 'source /opt/ros/jazzy/setup.bash; source /ws/install/setup.bash; exec "$@"' bash "$@"
}
case "${1:-help}" in
  setup)
    python3 -m venv "$state/venv"
    "$state/venv/bin/pip" install 'pyserial==3.5' 'websockets==15.0.1'
    docker build -t "$image" - < "$repo_root/scripts/Dockerfile.shake-lab"
    ;;
  start) start_lab live "${2:-}" ;;
  start-demo) start_lab replay ;;
  stop) stop_lab; echo 'Movement lab stopped; USB released.' ;;
  status) curl -fsS http://127.0.0.1:8080/api/state | python3 -c 'import sys,json; s=json.load(sys.stdin); s.pop("points"); print(json.dumps(s,indent=2))' ;;
  logs) docker logs --tail 60 "$container" ;;
  record|replay|demo|live)
    python3 - "$1" "${2:-}" <<'PYCONTROL'
import json
import sys
import time
from urllib.request import Request, urlopen
command, argument = sys.argv[1:]
action = {'demo': 'sample'}.get(command, command)
payload = {'action': action}
if command == 'record':
    payload['seconds'] = int(argument or 15)
if command == 'replay':
    payload['name'] = argument
request = Request('http://127.0.0.1:8080/api/action', json.dumps(payload).encode(),
                  {'Content-Type': 'application/json', 'X-Axiom-Lab': 'teaching'})
with urlopen(request, timeout=5) as response:
    print(json.load(response))
deadline = time.monotonic() + 180
while time.monotonic() < deadline:
    with urlopen('http://127.0.0.1:8080/api/state', timeout=5) as response:
        state = json.load(response)
    experiment = state['experiment']
    if experiment['error']:
        sys.exit(experiment['error'])
    if not experiment['busy']:
        if command == 'record' and not experiment['recording']:
            print(json.dumps(experiment['record_result'], indent=2)); break
        if command in ('demo', 'replay') and not experiment['processes'].get('player'):
            print(f"Replay complete: {state['samples']} messages, {state['count']} shake events."); break
        if command == 'live':
            print(experiment['notice']); break
    time.sleep(.3)
else:
    sys.exit('Action timed out; inspect the dashboard or logs.')
PYCONTROL
    ;;
  shell)
    owned_container || exit 1
    docker exec -it "$container" bash -c 'source /opt/ros/jazzy/setup.bash; source /ws/install/setup.bash; exec bash'
    ;;
  *) echo 'Usage: scripts/shake_lab.sh {setup|start [USB_PORT]|start-demo|status|logs|record [SECONDS]|replay BAG_NAME|demo|live|shell|stop}' ;;
esac
