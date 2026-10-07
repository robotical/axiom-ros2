"""HTTP connections must not stall state publication or disappear under a burst."""

from concurrent.futures import ThreadPoolExecutor
from http.client import HTTPConnection
import json
import socket
import threading

from axiom_marty_dashboard.web import Panel


def test_keep_alive_delivers_new_state_on_the_same_connection():
    panel = Panel("127.0.0.1", 0)
    connection = HTTPConnection("127.0.0.1", panel.server.server_port, timeout=2)
    try:
        panel.publish({"mode": "range", "value": 1})
        for asset, kind in (
            ("/graph.js", "text/javascript"),
            ("/graph.css", "text/css"),
            ("/command-info.js", "text/javascript"),
            ("/interface-info.js", "text/javascript"),
            ("/scenarios.js", "text/javascript"),
            ("/scenario-state.js", "text/javascript"),
            ("/scenarios.css", "text/css"),
        ):
            connection.request("GET", asset)
            response = connection.getresponse()
            assert response.status == 200 and kind in response.getheader("Content-Type")
            assert response.read()
        connection.request("GET", "/api/state")
        response = connection.getresponse()
        assert response.version == 11
        assert json.loads(response.read())["value"] == 1
        stream = connection.sock
        assert stream is not None
        panel.publish({"mode": "range", "value": 2})
        connection.request("GET", "/api/state")
        assert json.loads(connection.getresponse().read())["value"] == 2
        assert connection.sock is stream

        # An early rejected POST must close: its unread body cannot be another request.
        connection.request(
            "POST", "/api/unknown", body="{}", headers={"Content-Type": "application/json"}
        )
        response = connection.getresponse()
        assert response.status == 405 and response.will_close
        response.read()
    finally:
        connection.close()
        panel.close()


def test_slow_reader_and_connection_burst_do_not_block_fresh_state():
    panel = Panel("127.0.0.1", 0)
    address = ("127.0.0.1", panel.server.server_port)
    client = socket.create_connection(address, timeout=2)
    client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 1024)
    try:
        # Exceed the sender's socket buffer, then deliberately stop reading.
        panel.publish({"mode": "range", "padding": "x" * 8_000_000})
        client.sendall(b"GET /api/state HTTP/1.1\r\nHost: localhost\r\n\r\n")
        assert client.recv(1) == b"H"
        published = threading.Event()

        def publish():
            panel.publish({"mode": "range", "fresh": True})
            published.set()

        publisher = threading.Thread(target=publish, daemon=True)
        publisher.start()
        assert published.wait(1), "A slow HTTP reader must not hold the ROS state lock"

        def request(_):
            connection = HTTPConnection(*address, timeout=3)
            try:
                connection.request("GET", "/api/state")
                response = connection.getresponse()
                return response.status, json.loads(response.read())
            finally:
                connection.close()

        with ThreadPoolExecutor(max_workers=32) as executor:
            assert all(
                code == 200 and state["fresh"] for code, state in executor.map(request, range(64))
            )
    finally:
        client.close()
        panel.close()
