"""Connection state container for Axiom bridge.

Separated from the large `axiom_bridge_node` module for clarity.
"""

from __future__ import annotations

import threading
from typing import Optional

from .transports.serial import SerialTransport


class ConnectionState:
    """Holds current connection state (websocket or serial).

    This is a simple data container intentionally kept free of ROS imports so
    it can be reused or unit‑tested easily.
    """

    def __init__(self):
        # Unified state
        self.connected: bool = False
        self.uri: str = ''
        self.last_error: str = ''

        # WebSocket data (sensor JSON via /devjson)
        self.data_ws: Optional[object] = None
        self.data_thread: Optional[threading.Thread] = None

        # WebSocket control (RIC/REST via /ws)
        self.ctrl_ws: Optional[object] = None
        self.ctrl_thread: Optional[threading.Thread] = None

        # Handshake events for initial connect
        self._opened_event = threading.Event()
        self._error_event = threading.Event()

        # Serial transport
        self.serial_transport: Optional[SerialTransport] = None
