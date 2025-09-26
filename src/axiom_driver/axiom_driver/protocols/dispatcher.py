import threading
from typing import Callable, Dict, Optional

from axiom_driver.ric_consts import TYPE_RESPONSE, PROTO_RICREST, ELEM_CMDRESPJSON


class Dispatcher:
    """
    Matches RICREST responses by message number and forwards publishes to a handler.
    Provides a thread-safe waiter registry for simple RPC-style flows.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._next_msgnum = 1
        self._wait_ev: Dict[int, threading.Event] = {}
        self._wait_payload: Dict[int, bytes] = {}

        # Optional callback for non-response frames
        self.on_publish: Optional[Callable[[bytes], None]] = None

    def next_msgnum(self) -> int:
        with self._lock:
            n = self._next_msgnum
            self._next_msgnum = 1 if n >= 255 else n + 1
            return n

    def register_waiter(self, msgnum: int) -> threading.Event:
        ev = threading.Event()
        with self._lock:
            self._wait_ev[msgnum] = ev
            self._wait_payload.pop(msgnum, None)
        return ev

    def pop_payload(self, msgnum: int) -> bytes:
        with self._lock:
            self._wait_ev.pop(msgnum, None)
            return self._wait_payload.pop(msgnum, b'')

    def reset_waiters(self, reason: str = 'transport reset'):
        with self._lock:
            for ev in self._wait_ev.values():
                ev.set()
            self._wait_ev.clear()
            self._wait_payload.clear()

    def handle_frame(self, frame: bytes):
        if len(frame) < 3:
            return
        msgnum, typeproto, elem = frame[0], frame[1], frame[2]

        # RICREST response path
        if ((typeproto >> 6) & 0x3) == TYPE_RESPONSE and (typeproto & 0x3F) == PROTO_RICREST and elem == ELEM_CMDRESPJSON:
            body = frame[3:]
            # Strip optional NUL
            nul = body.find(b'\x00')
            body = body[:nul] if nul >= 0 else body
            with self._lock:
                ev = self._wait_ev.get(msgnum)
                if ev is not None:
                    self._wait_payload[msgnum] = body
                    ev.set()
            return

        # Otherwise, treat as publish/report and forward to on_publish
        cb = self.on_publish
        if cb:
            try:
                cb(frame)
            except Exception:
                self.get_logger().error('Error in on_publish callback')
                pass
