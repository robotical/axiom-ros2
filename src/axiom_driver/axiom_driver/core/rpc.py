"""Bounded, cancellable RICREST request correlation shared by all transports."""

from dataclasses import dataclass, field
import threading
import time


class SessionError(RuntimeError):
    """A request could not complete on the current connection."""


@dataclass
class Pending:
    event: threading.Event = field(default_factory=threading.Event)
    payload: bytes = None
    error: str = ''


class Requests:
    def __init__(self):
        self.lock = threading.Lock()
        self.pending = {}
        self.quarantine = {}
        self.next_id = 1

    def reserve(self):
        with self.lock:
            now = time.monotonic()
            for _ in range(255):
                number = self.next_id
                self.next_id = number % 255 + 1
                if number not in self.pending and self.quarantine.get(number, 0) <= now:
                    item = Pending()
                    self.pending[number] = item
                    return number, item
        raise SessionError('All RPC message numbers are in use')

    def resolve(self, number, payload):
        with self.lock:
            item = self.pending.get(number)
            if item is not None and not item.event.is_set():
                item.payload = payload
                item.event.set()
                return True
        return False

    def cancel_all(self, reason):
        with self.lock:
            for item in self.pending.values():
                item.error = reason
                item.event.set()
            self.pending.clear()

    def finish(self, number, item, timeout, send):
        try:
            send()
            if not item.event.wait(timeout):
                with self.lock:
                    self.quarantine[number] = time.monotonic() + max(5, timeout * 2)
                raise SessionError('RPC timed out')
            if item.error:
                raise SessionError(item.error)
            if item.payload is None:
                raise SessionError('RPC completed without a response')
            return item.payload
        finally:
            with self.lock:
                if self.pending.get(number) is item:
                    self.pending.pop(number)
