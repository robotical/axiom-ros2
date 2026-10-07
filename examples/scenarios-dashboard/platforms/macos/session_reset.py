#!/usr/bin/env python3
"""Reset only this project's learning container; ROS never depends on this adapter."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid
from urllib.request import urlopen

NAME = "axiom-marty-demo"


def write_status(directory, **state):
    directory.mkdir(parents=True, exist_ok=True)
    temporary = directory / "status.tmp"
    temporary.write_text(json.dumps({
        "available": True, "updated": time.time(),
        "command": "python3 /demo/platforms/macos/session_reset.py request", **state,
    }))
    temporary.replace(directory / "status.json")


def assert_learning_owned(root):
    mode = json.loads((root / ".runtime/demo.json").read_text()).get("demo")
    if mode != "learning":
        raise RuntimeError("Reset is available only in the manual learning workstation")
    result = subprocess.run([
        "docker", "inspect", "-f",
        '{{index .Config.Labels "com.robotical.axiom-marty-demo"}}|{{.Id}}', NAME,
    ], capture_output=True, text=True, timeout=5, check=True)
    identity = result.stdout.strip().split("|", 1)
    if len(identity) != 2 or identity[0] != "true" or len(identity[1]) != 64:
        raise RuntimeError("Refusing to reset a container not owned by this project")
    return identity[1]


def stop_nodes():
    # Give actual ROS nodes SIGINT before Docker closes their terminal/PTY sessions.
    # Container restart then removes shells, background jobs, daemons and retained DDS state.
    targets = []
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        try:
            args = (entry / "cmdline").read_bytes().decode().split("\0")
            executable = args[1] if "python" in Path(args[0]).name and len(args) > 1 else args[0]
            installed = executable.startswith(("/ws/install/", "/opt/ros/jazzy/lib/"))
            console = executable == "/opt/ros/jazzy/bin/ros2" and not any(
                arg in ("run", "launch") for arg in args[2:3]
            )
            if (installed or console) and "axiom_marty_dashboard" not in executable:
                pid = int(entry.name)
                os.kill(pid, signal.SIGINT)
                targets.append(entry)
        except (OSError, UnicodeError, IndexError):
            continue
    deadline = time.monotonic() + 8
    while any(p.exists() for p in targets) and time.monotonic() < deadline:
        time.sleep(0.1)


def restart(root):
    container = assert_learning_owned(root)
    subprocess.run([
        "docker", "exec", container, "python3",
        "/demo/platforms/macos/session_reset.py", "stop-nodes",
    ], timeout=12, check=True)
    subprocess.run(["docker", "restart", "--signal", "SIGINT", "--timeout", "15", container],
                   timeout=45, check=True)
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        try:
            with urlopen("http://127.0.0.1:8083/api/state", timeout=1) as response:
                state = json.load(response)
            if state.get("commands") and state.get("graph", {}).get("available"):
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    raise RuntimeError("The guide did not become ready after restart; inspect docker logs")


def watch(root):
    directory = root / ".runtime/ws/.session-reset"
    request_file = directory / "request.json"
    state = {"phase": "ready", "request_id": "", "error": "", "completed_at": 0}
    while True:
        write_status(directory, **state)
        try:
            request = json.loads(request_file.read_text())
            identifier = request["id"]
            if not isinstance(identifier, str) or uuid.UUID(hex=identifier).hex != identifier:
                raise ValueError("Invalid reset identifier")
        except FileNotFoundError:
            time.sleep(0.5)
            continue
        except (ValueError, KeyError, TypeError) as exc:
            request_file.unlink(missing_ok=True)
            state = {**state, "phase": "error", "error": str(exc)}
            continue
        state = {**state, "phase": "resetting", "request_id": identifier, "error": ""}
        write_status(directory, **state)
        request_file.unlink()
        try:
            restart(root)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            state = {**state, "phase": "error", "error": str(exc)}
        else:
            state = {**state, "phase": "ready", "completed_at": time.time()}


def request(directory):
    status = json.loads((directory / "status.json").read_text())
    if not status["available"] or not 0 <= time.time() - status["updated"] < 3:
        raise RuntimeError("Workstation supervisor unavailable")
    if status["phase"] == "resetting":
        raise RuntimeError("A reset is already in progress")
    identifier = uuid.uuid4().hex
    temporary = directory / (identifier + ".tmp")
    temporary.write_text(json.dumps({"id": identifier}))
    try:
        os.link(temporary, directory / "request.json")
    finally:
        temporary.unlink(missing_ok=True)
    print("Restart requested. This terminal will close; start nodes again in the fresh terminals.")


def start_controller(root):
    stop_controller(root)
    directory = root / ".runtime/ws/.session-reset"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "request.json").unlink(missing_ok=True)
    with (root / ".runtime/session-reset.log").open("w") as output:
        child = subprocess.Popen([
            os.sys.executable, "-u", str(Path(__file__).resolve()), "watch", "--root", str(root),
        ], stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    (root / ".runtime/session-controller.json").write_text(json.dumps({"pid": child.pid}))


def stop_controller(root):
    record = root / ".runtime/session-controller.json"
    if not record.exists():
        return
    pid = json.loads(record.read_text())["pid"]
    result = subprocess.run(["ps", "-p", str(pid), "-o", "command="], capture_output=True,
                            text=True, check=False)
    if str(Path(__file__).resolve()) in result.stdout and str(root) in result.stdout:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    record.unlink(missing_ok=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=["watch", "request", "stop-nodes"])
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument("--directory", type=Path, default=Path("/ws/.session-reset"))
    args = parser.parse_args()
    if args.operation == "watch":
        watch(args.root)
    elif args.operation == "request":
        request(args.directory)
    else:
        stop_nodes()
