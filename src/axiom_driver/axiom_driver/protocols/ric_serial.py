"""Bounded streaming MiniHDLC framing, independent of ROS."""

import threading


class RICSerial:
    def __init__(self, hdlc, max_frame_bytes=262144):
        self._hdlc = hdlc
        self._buf = bytearray()
        self._lock = threading.Lock()
        self._limit = max_frame_bytes
        self.on_frame = None
        self.on_error = None

    def encode(self, inner):
        return self._hdlc.encode(inner)

    def reset(self):
        with self._lock:
            self._buf.clear()

    def feed_bytes(self, chunk):
        frames, errors = [], []
        with self._lock:
            for byte in chunk:
                if byte == self._hdlc.flag:
                    if len(self._buf) > 1:
                        framed = bytes(self._buf) + bytes([byte])
                        ok, payload = self._hdlc.try_decode(framed)
                        if ok:
                            frames.append(payload)
                        else:
                            errors.append('HDLC CRC/framing error')
                    self._buf[:] = bytes([byte])  # Shared closing/opening delimiter.
                elif self._buf:
                    self._buf.append(byte)
                    if len(self._buf) > self._limit:
                        self._buf.clear()
                        errors.append('HDLC frame exceeds size limit')
        # Callbacks may reset/send; never invoke them under the framing lock.
        for message in errors:
            if self.on_error:
                self.on_error(message)
        for frame in frames:
            if self.on_frame:
                self.on_frame(frame)
