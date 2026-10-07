"""ROS snapshots and an explicitly configured workstation reset; no ROS control pathway."""

from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib.resources import files
import json
import secrets
import threading
from urllib.parse import urlsplit

from .command_help import explain


class DashboardServer(ThreadingHTTPServer):
    # Browser preconnections and Docker forwarding can arrive together.
    request_queue_size = 128


class Panel:
    def __init__(self, host, port, reset=None):
        self.lock = threading.Lock()
        self.state = {}
        self.reset = reset
        self.reset_token = secrets.token_urlsafe(32)
        panel = self
        html = files("axiom_marty_dashboard").joinpath("dashboard.html").read_bytes()
        assets = {
            "/scenario-state.js": (
                files("axiom_marty_dashboard").joinpath("scenario-state.js").read_bytes(),
                "text/javascript; charset=utf-8",
            ),
            "/scenarios.css": (
                files("axiom_marty_dashboard").joinpath("scenarios.css").read_bytes(),
                "text/css; charset=utf-8",
            ),
            "/session.js": (
                files("axiom_marty_dashboard").joinpath("session.js").read_bytes(),
                "text/javascript; charset=utf-8",
            ),
            "/command-info.js": (
                files("axiom_marty_dashboard").joinpath("command-info.js").read_bytes(),
                "text/javascript; charset=utf-8",
            ),
            "/interface-info.js": (
                files("axiom_marty_dashboard").joinpath("interface-info.js").read_bytes(),
                "text/javascript; charset=utf-8",
            ),
            "/scenarios.js": (
                files("axiom_marty_dashboard").joinpath("scenarios.js").read_bytes(),
                "text/javascript; charset=utf-8",
            ),
            "/graph.js": (
                files("axiom_marty_dashboard").joinpath("graph.js").read_bytes(),
                "text/javascript; charset=utf-8",
            ),
            "/graph.css": (
                files("axiom_marty_dashboard").joinpath("graph.css").read_bytes(),
                "text/css; charset=utf-8",
            ),
        }

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            timeout = 5

            def log_message(self, *args):
                pass

            def handle(self):
                try:
                    super().handle()
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def respond(self, code, payload, content_type="application/json"):
                data = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                # Rejected requests may have an unread body; do not reuse their stream.
                if code >= 400:
                    self.close_connection = True
                try:
                    self.send_response(code)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Content-Length", str(len(data)))
                    if self.close_connection:
                        self.send_header("Connection", "close")
                    self.end_headers()
                    self.wfile.write(data)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def do_GET(self):
                if self.path == "/":
                    self.respond(200, html, "text/html; charset=utf-8")
                elif self.path in assets:
                    self.respond(200, *assets[self.path])
                elif self.path == "/api/state":
                    with panel.lock:
                        state = panel.state
                    self.respond(200, state)
                else:
                    self.respond(404, {"message": "Not found"})

            def reject_write(self):
                self.respond(405, {"message": "Read-only dashboard; use the ROS console"})

            def do_POST(self):
                if self.path != "/api/session/reset" or panel.reset is None:
                    self.reject_write()
                    return
                # A same-origin page must supply its unpredictable session token.
                origin = "http://" + self.headers.get("Host", "")
                try:
                    local = urlsplit(origin).hostname in ("127.0.0.1", "localhost", "::1")
                except ValueError:
                    local = False
                if (
                    not local
                    or self.headers.get("Origin") != origin
                    or not secrets.compare_digest(
                        self.headers.get("X-Session-Token", "").encode(), panel.reset_token.encode()
                    )
                ):
                    self.respond(403, {"message": "Invalid reset origin or token"})
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if not 0 < length <= 32 or json.loads(self.rfile.read(length)) != {}:
                        raise ValueError("Reset accepts no command arguments")
                except (ValueError, TypeError):
                    self.respond(400, {"message": "Reset accepts only an empty JSON object"})
                    return
                try:
                    result = panel.reset.request()
                except (RuntimeError, FileExistsError) as exc:
                    self.respond(409, {"message": str(exc)})
                except OSError as exc:
                    self.respond(503, {"message": str(exc)})
                else:
                    self.respond(202, result)

            do_PUT = do_PATCH = do_DELETE = reject_write

        self.server = DashboardServer((host, port), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def publish(self, state):
        if self.reset is not None:
            session = self.reset.status()
            state = {**state, "session": {**session, "token": self.reset_token}}
            if session.get("command"):
                state["commands"] = [
                    *state.get("commands", []),
                    {
                        "group": "Workstation",
                        "title": "Start from scratch",
                        "command": session["command"],
                        "note": "Stops this session and reopens four empty "
                        "terminals and the guide.",
                        "help": explain("Start from scratch", session["command"]),
                    },
                ]
        with self.lock:
            self.state = state

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(2)
