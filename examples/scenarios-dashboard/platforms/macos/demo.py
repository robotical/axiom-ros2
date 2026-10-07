#!/usr/bin/env python3
"""Own only this demo's container and required USB relays."""

import argparse
import json
import os
import re
from pathlib import Path
import signal
import shlex
import socket
import subprocess
import sys
import time

from session_reset import request as request_reset, start_controller, stop_controller

ROOT = Path(__file__).resolve().parents[2]
MAC = Path(__file__).resolve().parent
AXIOM = Path(os.environ.get("AXIOM_ROS_ROOT", ROOT.parents[1]))
MARTY = Path(os.environ.get("MARTY_ROS_ROOT", AXIOM.parent / "marty-ros2"))
STATE = ROOT / ".runtime"
NAME = "axiom-marty-demo"
IMAGE = "axiom-marty-demo:jazzy"
CORE_IMAGE = "axiom-marty-demo-core:jazzy"
# Keep the dashboard clear of React Native Metro and development simulator clients.
PANEL_PORT = 8083


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def owned_container():
    result = subprocess.run(
        [
            "docker",
            "inspect",
            "-f",
            '{{index .Config.Labels "com.robotical.axiom-marty-demo"}}',
            NAME,
        ],
        capture_output=True,
        text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def stop():
    if owned_container():
        try:
            subprocess.run(
                [
                    "docker",
                    "exec",
                    NAME,
                    "python3",
                    "/demo/platforms/macos/session_reset.py",
                    "stop-nodes",
                ],
                timeout=12,
                check=False,
            )
        except subprocess.TimeoutExpired:
            print("Node shutdown timed out; stopping the workstation container.", file=sys.stderr)
        subprocess.run(["docker", "kill", "--signal=SIGINT", NAME], capture_output=True)
        subprocess.run(["docker", "stop", "-t", "15", NAME], capture_output=True)
        subprocess.run(["docker", "rm", NAME], capture_output=True)
    stop_controller(ROOT)
    record = STATE / "relays.json"
    if record.exists():
        for relay in json.loads(record.read_text()):
            result = subprocess.run(
                ["ps", "-p", str(relay["pid"]), "-o", "command="], capture_output=True, text=True
            )
            identity = relay.get("identity", relay.get("port", ""))
            if relay["script"] in result.stdout and identity and identity in result.stdout:
                try:
                    os.kill(relay["pid"], signal.SIGTERM)
                except ProcessLookupError:
                    pass
        record.unlink()
    print("Demo stopped")


def available(port):
    with socket.socket() as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind(("127.0.0.1", port))


def relay(script, args, log, identity):
    with (STATE / log).open("wb") as out:
        child = subprocess.Popen(
            [sys.executable, "-u", str(script), *args],
            stdout=out,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    return {"pid": child.pid, "script": str(script), "identity": identity}


def start(args):
    if owned_container():
        print("Demo already exists. Use status or stop before starting again.")
        return
    STATE.mkdir(parents=True, exist_ok=True)
    if (STATE / "relays.json").exists():
        stop()
    axioms = axiom_connections(args)
    ports = [*[port for _, port, _ in axioms], 6080]
    if args.with_dashboard:
        ports.append(PANEL_PORT)
    if not args.marty_ip:
        ports.append(8785)
    for port in ports:
        available(port)
    print("Starting Linux workstation; run ROS commands yourself.", flush=True)
    run(
        "docker",
        "build",
        "-t",
        CORE_IMAGE,
        "-f",
        str(ROOT / "scripts/Dockerfile"),
        str(ROOT / "scripts"),
    )
    run("docker", "build", "-t", IMAGE, "-f", str(MAC / "Dockerfile"), str(MAC))
    relays = []
    try:
        devices = [("axiom", port, explicit) for _, port, explicit in axioms]
        if not args.marty_ip:
            devices.append(("marty", 8785, args.marty_port))
        for kind, port, explicit in devices:
            relay_args = ["--kind", kind, "--listen-port", str(port)]
            if explicit:
                relay_args += ["--port", explicit]
            relays.append(
                relay(
                    MAC / "usb_ws_relay.py",
                    relay_args,
                    f"{kind}-{port}-relay.log",
                    f"--listen-port {port}",
                )
            )
            (STATE / "relays.json").write_text(json.dumps(relays))
        time.sleep(0.5)
        for child in relays:
            os.kill(child["pid"], 0)
        options = ["--demo", args.demo]
        if args.with_dashboard:
            options += ["--with-dashboard", f"dashboard_port:={PANEL_PORT}"]
        (STATE / "demo.json").write_text(json.dumps({"demo": args.demo}))
        if args.demo == "learning":
            start_controller(ROOT)
        if args.marty_ip:
            options += ["--marty-ip", args.marty_ip]
        gui_ports = ["-p", f"127.0.0.1:{PANEL_PORT}:{PANEL_PORT}"] if args.with_dashboard else []
        build_target = " axiom_marty_dashboard" if args.with_dashboard else ""
        run(
            "docker",
            "run",
            "-d",
            "--init",
            "--name",
            NAME,
            "--label",
            "com.robotical.axiom-marty-demo=true",
            *gui_ports,
            "-p",
            "127.0.0.1:6080:6080",
            "-e",
            "ROS_DOMAIN_ID=43",
            "-e",
            "ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST",
            "-e",
            "AXIOM_ROS_TRANSPORT=ws",
            "-e",
            "AXIOM_ROS_URI=ws://host.docker.internal:8765/ws",
            "-e",
            "AXIOM_ROS_BOARDS_FILE=/ws/axioms.yaml",
            "-e",
            "AXIOM_ROS_BOARDS="
            + json.dumps(
                {
                    name: {"transport": "ws", "device_uri": f"ws://host.docker.internal:{port}/ws"}
                    for name, port, _ in axioms
                }
            ),
            "-e",
            "MARTY_ROS_METHOD=wifi",
            "-e",
            f"MARTY_ROS_LOCATOR={args.marty_ip or 'host.docker.internal'}",
            "-e",
            f"MARTY_ROS_WIFI_PORT={80 if args.marty_ip else 8785}",
            "-v",
            f"{AXIOM}:/axiom:ro",
            "-v",
            f"{MARTY}:/marty:ro",
            "-v",
            f"{ROOT}:/demo:ro",
            "-v",
            f"{NAME}-browser:/home/ubuntu/.axiom-dashboard",
            "-v",
            f"{STATE / 'ws'}:/ws",
            IMAGE,
            "bash",
            "-lc",
            "set -eo pipefail\n"
            "bash /demo/scripts/build_workspace.sh" + build_target + "\n"
            "source /opt/ros/jazzy/setup.bash\n"
            "source /ws/install/setup.bash\n"
            'exec python3 /demo/platforms/macos/container_demo.py "$@"',
            "demo",
            *options,
        )
    except BaseException:
        stop()
        raise
    print(
        (
            f"Dashboard port available: http://127.0.0.1:{PANEL_PORT}\n"
            if args.with_dashboard
            else ""
        )
        + "Linux desktop: http://127.0.0.1:6080/desktop.html\n"
        f"Logs: docker logs -f {shlex.quote(NAME)}",
        flush=True,
    )


def status():
    if not owned_container():
        print("Demo is stopped")
        return
    print("Linux desktop: http://127.0.0.1:6080/desktop.html")
    print("Guide: http://127.0.0.1:8083 · ROS nodes and acquisition are manual.")


def axiom_connections(args):
    if not args.axiom:
        return [("axiom", 8765, args.axiom_port)]
    if args.axiom_port:
        raise ValueError("Use --axiom NAME=PORT or --axiom-port, not both")
    result = []
    for item in args.axiom:
        name, separator, port = item.partition("=")
        if not separator or not re.fullmatch("[a-zA-Z][a-zA-Z0-9_]*", name) or not port:
            raise ValueError("--axiom requires NAME=/dev/cu.PORT")
        result.append(("axiom/" + name, 8765 + len(result), port))
    if len({name for name, _, _ in result}) != len(result):
        raise ValueError("Axiom names must be unique")
    if len({port for _, _, port in result}) != len(result):
        raise ValueError("Each Axiom needs a different USB port")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["start", "stop", "status", "reset"])
    parser.add_argument("--axiom-port")
    parser.add_argument(
        "--axiom",
        action="append",
        default=[],
        metavar="NAME=PORT",
        help="Repeat for multiple USB boards, e.g. --axiom front=/dev/cu.usbmodem2101",
    )
    parser.add_argument(
        "--with-dashboard",
        action="store_true",
        help="Start the optional read-only browser guide; device and demo nodes remain manual",
    )
    marty = parser.add_mutually_exclusive_group()
    marty.add_argument("--marty-port", help="Marty USB serial port")
    marty.add_argument("--marty-ip", help="Connect directly to Marty over Wi-Fi (port 80)")
    parser.add_argument("--demo", choices=["learning"], default="learning")
    args = parser.parse_args()
    if args.command == "start":
        start(args)
    elif args.command == "stop":
        stop()
    elif args.command == "reset":
        request_reset(STATE / "ws/.session-reset")
    else:
        status()
