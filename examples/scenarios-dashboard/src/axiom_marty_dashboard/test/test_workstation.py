"""The opt-in lifecycle action is fixed, same-origin, and cannot queue duplicate resets."""

from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
import json
import time

import pytest

from axiom_marty_dashboard.web import Panel
from axiom_marty_dashboard.workstation import WorkstationReset


def ready(directory):
    (directory / "status.json").write_text(
        json.dumps(
            {
                "available": True,
                "phase": "ready",
                "updated": time.time(),
                "command": "python3 /demo/platforms/macos/session_reset.py request",
            }
        )
    )


def test_reset_endpoint_is_opt_in_fixed_same_origin_and_single_request(tmp_path):
    ready(tmp_path)
    panel = Panel("127.0.0.1", 0, reset=WorkstationReset(tmp_path))
    connection = HTTPConnection("127.0.0.1", panel.server.server_port, timeout=2)
    origin = "http://127.0.0.1:" + str(panel.server.server_port)
    try:
        panel.publish({"commands": []})
        connection.request("GET", "/api/state")
        state = json.loads(connection.getresponse().read())
        headers = {"Origin": origin, "X-Session-Token": state["session"]["token"]}
        assert state["commands"][0]["group"] == "Workstation"
        for invalid in (
            {},
            {**headers, "Origin": "https://unrelated.example"},
            {**headers, "X-Session-Token": "incorrect"},
            {**headers, "Host": "unrelated.example", "Origin": "http://unrelated.example"},
        ):
            connection.request("POST", "/api/session/reset", "{}", invalid)
            response = connection.getresponse()
            assert response.status == 403
            response.read()
        assert not (tmp_path / "request.json").exists()
        connection.request("POST", "/api/session/reset", '{"command":"anything"}', headers)
        response = connection.getresponse()
        assert response.status == 400
        response.read()
        connection.request("POST", "/api/session/reset", "{}", headers)
        response = connection.getresponse()
        assert response.status == 202
        result = json.loads(response.read())
        assert json.loads((tmp_path / "request.json").read_text())["id"] == result["id"]
        connection.request("POST", "/api/session/reset", "{}", headers)
        response = connection.getresponse()
        assert response.status == 409
        response.read()
        connection.request("POST", "/api/enable", "{}", headers)
        response = connection.getresponse()
        assert response.status == 405
        response.read()
    finally:
        connection.close()
        panel.close()


def test_separate_guides_cannot_race_to_queue_two_resets(tmp_path):
    ready(tmp_path)

    def request(_):
        try:
            return WorkstationReset(tmp_path).request()["id"]
        except (RuntimeError, FileExistsError):
            return None

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(request, range(8)))
    assert len([r for r in results if r]) == 1
    assert not list(tmp_path.glob("*.tmp"))
    (tmp_path / "request.json").unlink()
    (tmp_path / "status.json").write_text(
        json.dumps(
            {
                "available": True,
                "phase": "ready",
                "updated": time.time() - 20,
            }
        )
    )
    reset = WorkstationReset(tmp_path)
    assert not reset.status()["enabled"]
    with pytest.raises(OSError):
        reset.request()


def test_native_guide_has_no_lifecycle_endpoint():
    panel = Panel("127.0.0.1", 0)
    connection = HTTPConnection("127.0.0.1", panel.server.server_port, timeout=2)
    try:
        panel.publish({"commands": []})
        connection.request("GET", "/api/state")
        assert "session" not in json.loads(connection.getresponse().read())
        connection.request("POST", "/api/session/reset", "{}")
        response = connection.getresponse()
        assert response.status == 405
        response.read()
    finally:
        connection.close()
        panel.close()
