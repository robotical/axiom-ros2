# axiom_driver/protocols/ric_serial.py

import threading
from typing import Callable, Optional
from axiom_driver.mini_hdlc import MiniHDLC

class RICSerial:
    """
    Mini-HDLC wrapper around inner RIC frames (RICFrame).
    - encode(inner) -> bytes: produces a full HDLC frame (CRC, flags, escapes)
    - feed_bytes(chunk): streaming deframer; calls on_frame(payload) for each decoded RICFrame
    """

    def __init__(self, hdlc: MiniHDLC):
        self._hdlc = hdlc
        self._buf = bytearray()
        self._lock = threading.Lock()

        # Callbacks set by the owner:
        self.on_frame: Optional[Callable[[bytes], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

    # ------------- TX -------------
    def encode(self, inner: bytes) -> bytes:
        """Wrap an inner RIC frame with Mini-HDLC framing (CRC, escapes, flags)."""
        return self._hdlc.encode(inner)

    # ------------- RX (streaming) -------------
    def feed_bytes(self, chunk: bytes):
        """
        Feed raw bytes from the transport (already de-tunneled if OverAscii is in use).
        Extracts complete HDLC frames between flags and delivers the inner payload to on_frame().
        """
        if not chunk:
            return
        with self._lock:
            self._buf.extend(chunk)
            flag = self._hdlc.flag

            while True:
                # Find opening flag
                try:
                    start = self._buf.index(flag)
                except ValueError:
                    # No flag present → this buffer doesn't contain HDLC; drop it
                    if self._buf and self.on_error:
                        try:
                            self.on_error(f'No HDLC flag found in {len(self._buf)}B chunk; dropping')
                        except Exception:
                            pass
                    self._buf.clear()
                    return

                # Trim leading noise before the first flag
                if start > 0:
                    del self._buf[:start]

                # Find closing flag after the first byte
                try:
                    end = self._buf.index(flag, 1)
                except ValueError:
                    # Incomplete frame (only one flag so far) → wait for more bytes
                    return

                framed = bytes(self._buf[: end + 1])  # inclusive of trailing flag
                del self._buf[: end + 1]

                ok, payload = self._hdlc.try_decode(framed)
                if ok and payload:
                    cb = self.on_frame
                    if cb:
                        try:
                            cb(payload)
                        except Exception:
                            pass
                else:
                    err = self.on_error
                    if err:
                        try:
                            err(f'HDLC decode failed len={len(framed)}')
                        except Exception:
                            pass
                # Loop to see if the buffer already contains another frame