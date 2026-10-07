"""Optional fixed-operation mailbox for a workstation supervisor, independent of ROS."""

import json
import os
from pathlib import Path
import threading
import time
import uuid


class WorkstationReset:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.lock = threading.Lock()

    def status(self):
        try:
            state = json.loads((self.directory / "status.json").read_text())
            age = time.time() - state["updated"]
            limit = 120 if state["phase"] == "resetting" else 3
            if not 0 <= age < limit or not state["available"]:
                raise ValueError("Workstation supervisor unavailable")
            return {"enabled": True, **state}
        except (OSError, ValueError, KeyError, TypeError):
            return {"enabled": False, "phase": "unavailable"}

    def request(self):
        with self.lock:
            state = self.status()
            if not state["enabled"]:
                raise OSError("Workstation supervisor unavailable")
            request = self.directory / "request.json"
            if state["phase"] == "resetting" or request.exists():
                raise RuntimeError("A reset is already in progress")
            identifier = uuid.uuid4().hex
            # Exclusive creation prevents two guide processes queuing separate resets.
            temporary = self.directory / (identifier + ".tmp")
            temporary.write_text(json.dumps({"id": identifier}))
            try:
                os.link(temporary, request)
            finally:
                temporary.unlink(missing_ok=True)
            return {"id": identifier}
