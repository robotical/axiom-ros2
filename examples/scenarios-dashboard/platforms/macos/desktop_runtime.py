"""Supervise the optional Linux desktop and its browser transport."""

import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import urllib.request
import xml.etree.ElementTree as ET


class DesktopRuntime:
    # Applications can be closed and reopened from the taskbar. Only session
    # services determine whether the desktop itself is available.
    services = {"display", "window-manager", "panel", "vnc", "web-viewer"}

    def __init__(self, dashboard_port=8083, auto_apps=True):
        self.children = []
        self.logs = []
        self.error = "Linux desktop is starting"
        self.status = Path("/tmp/axiom-rviz-status.json")
        self.env = {
            **os.environ,
            "DISPLAY": ":99",
            "QT_X11_NO_MITSHM": "1",
            "LIBGL_ALWAYS_SOFTWARE": "1",
        }
        self.dashboard_port = dashboard_port
        self.auto_apps = auto_apps
        self.dashboard_started = False
        self.publish()

    def spawn(self, name, arguments):
        log = open("/tmp/axiom-" + name + ".log", "w")
        self.logs.append(log)
        child = subprocess.Popen(
            arguments, env=self.env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True
        )
        self.children.append((name, child))
        return child

    def start(self):
        try:
            web = Path("/tmp/axiom-desktop-web")
            web.mkdir(exist_ok=True)
            for name in ("core", "vendor"):
                target = web / name
                if not target.exists():
                    target.symlink_to(Path("/usr/share/novnc") / name, target_is_directory=True)
            source = Path(__file__).resolve().parent
            shutil.copyfile(source / "desktop.html", web / "desktop.html")
            shutil.copyfile(source / "clipboard.js", web / "clipboard.js")
            # Keep existing viewer bookmarks working.
            shutil.copyfile(source / "desktop.html", web / "rviz.html")
            self.prepare_apps(source)
            self.spawn(
                "display",
                [
                    "Xvfb",
                    ":99",
                    "-screen",
                    "0",
                    "1600x900x24",
                    "-nolisten",
                    "tcp",
                    "+extension",
                    "GLX",
                    "+render",
                    "-noreset",
                ],
            )
            deadline = time.monotonic() + 8
            while time.monotonic() < deadline:
                result = subprocess.run(
                    ["xdpyinfo"],
                    env=self.env,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=2,
                )
                if result.returncode == 0:
                    break
                time.sleep(0.1)
            else:
                raise RuntimeError("Linux display failed to start")
            self.spawn("window-manager", ["openbox", "--config-file", "/tmp/axiom-openbox.xml"])
            subprocess.run(["xsetroot", "-solid", "#26333d"], env=self.env, check=True)
            self.spawn("panel", ["tint2", "-c", "/tmp/axiom-tint2rc"])
            self.spawn(
                "vnc",
                [
                    "x11vnc",
                    "-display",
                    ":99",
                    "-localhost",
                    "-rfbport",
                    "5900",
                    "-forever",
                    "-shared",
                    "-nopw",
                    "-noxdamage",
                    "-skip_lockkeys",
                    "-quiet",
                ],
            )
            self.spawn(
                "web-viewer", ["websockify", "--web", str(web), "0.0.0.0:6080", "127.0.0.1:5900"]
            )
            if self.auto_apps:
                self.spawn("rviz", [str(source / "desktop/app.sh"), "rviz"])
            if not self.auto_apps:
                self.spawn("terminal", [str(source / "desktop/app.sh"), "terminal", "tmux"])
            else:
                self.spawn("terminal", [str(source / "desktop/app.sh"), "terminal"])
            self.error = ""
        except (
            OSError,
            RuntimeError,
            subprocess.TimeoutExpired,
            subprocess.CalledProcessError,
        ) as exc:
            self.error = str(exc)
        self.publish()

    def prepare_apps(self, source):
        # Retain Openbox's normal window controls and key bindings.
        namespace = "{http://openbox.org/3.4/rc}"
        wm = ET.parse("/etc/xdg/openbox/rc.xml")
        root = wm.getroot()
        root.remove(root.find(namespace + "applications"))
        root.append(ET.parse(source / "desktop/windows.xml").getroot())
        if not self.auto_apps:
            terminal = root.find(
                namespace + "applications/" + namespace + "application[@class='AxiomTerminal']"
            )
            if self.dashboard_port:
                terminal.find(namespace + "position/" + namespace + "y").text = "0"
                terminal.find(namespace + "size/" + namespace + "width").text = "956"
                terminal.find(namespace + "size/" + namespace + "height").text = "866"
            else:
                terminal.remove(terminal.find(namespace + "position"))
                terminal.remove(terminal.find(namespace + "size"))
                ET.SubElement(terminal, namespace + "maximized").text = "yes"
        root.find(namespace + "desktops/" + namespace + "number").text = "1"
        menu = root.find(namespace + "menu")
        for item in list(menu.findall(namespace + "file")):
            menu.remove(item)
        ET.SubElement(menu, namespace + "file").text = str(source / "desktop/menu.xml")
        wm.write("/tmp/axiom-openbox.xml")
        config = Path("/ws/install/axiom_marty_demo/share/axiom_marty_demo/config/sensors.rviz")
        # Desktop layout is an adapter preference; leave the native RViz config intact.
        Path("/tmp/axiom-desktop.rviz").write_text(
            config.read_text().replace(
                "Width: 1280\n  Height: 720\n  X: 0\n  Y: 0",
                "Width: 956\n  Height: 614\n  X: 642\n  Y: 0",
            )
        )
        panel_config = (source / "desktop/tint2rc").read_text()
        if not self.dashboard_port:
            panel_config = "\n".join(
                line for line in panel_config.splitlines() if "dashboard.desktop" not in line
            )
        Path("/tmp/axiom-tint2rc").write_text(panel_config)
        Path("/tmp/axiom-dashboard-url").write_text(
            f"http://127.0.0.1:{self.dashboard_port}/#sensors-only"
        )
        profile = Path("/home/ubuntu/.axiom-dashboard")
        profile.mkdir(exist_ok=True)
        shutil.copyfile(source / "desktop/firefox.js", profile / "user.js")
        shutil.chown(profile, user="ubuntu", group="ubuntu")

    def open_dashboard_when_ready(self):
        if self.dashboard_started or self.error or not self.dashboard_port:
            return
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.dashboard_port}/api/state", timeout=0.2
            ):
                pass
        except OSError:
            return
        self.spawn("dashboard", [str(Path(__file__).with_name("desktop") / "app.sh"), "dashboard"])
        self.dashboard_started = True

    def publish(self):
        running = {name for name, child in self.children if child.poll() is None}
        failed = self.services - running
        error = self.error or (
            "Desktop service stopped: " + ", ".join(sorted(failed)) if failed else ""
        )
        data = {
            "available": not error,
            "url": "http://127.0.0.1:6080/desktop.html",
            "error": error,
            "updated": time.time(),
        }
        temporary = self.status.with_suffix(".tmp")
        temporary.write_text(json.dumps(data))
        temporary.replace(self.status)

    def close(self):
        for _, child in reversed(self.children):
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        deadline = time.monotonic() + 3
        for _, child in reversed(self.children):
            try:
                child.wait(max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
        for log in self.logs:
            log.close()
        self.error = "Linux desktop stopped"
        self.publish()
