import threading
from typing import Callable, Optional
import rclpy.logging
logger = rclpy.logging.get_logger("Transport")

class Transport:
    """
    Abstract transport interface.

    Subclasses implement start(), stop(), and send(bytes), and invoke the
    callbacks whenever data arrives or status changes.
    """

    def __init__(self):
    # Callbacks set by the owner (node/protocol):
        self.on_bytes: Optional[Callable[[bytes], None]] = None
        self.on_text: Optional[Callable[[str], None]] = None
        self.on_status: Optional[Callable[[bool, str], None]] = None

        # Common guard for lifecycle
        self._lock = threading.Lock()
        self._running = False

    # Lifecycle
    def start(self):  # pragma: no cover - interface
        raise NotImplementedError

    def stop(self):  # pragma: no cover - interface
        raise NotImplementedError

    # Outbound
    def send(self, data: bytes):  # pragma: no cover - interface
        raise NotImplementedError

    # Helper to emit status
    def _emit_status(self, connected: bool, msg: str = ""):
        cb = self.on_status
        if cb:
            try:
                cb(connected, msg)
            except Exception:
                logger.error('Error in on_status callback')
                pass

    # Helper to emit bytes
    def _emit_bytes(self, data: bytes):
        cb = self.on_bytes
        if cb and data:
            try:
                cb(data)
            except Exception:
                logger.error('Error in on_status callback')
                pass

    # Helper to emit text
    def _emit_text(self, text: str):
        cb = self.on_text
        if cb and text:
            try:
                cb(text)
            except Exception:
                logger.error('Error in on_status callback')
                pass
