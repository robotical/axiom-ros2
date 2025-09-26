import threading
import queue
import time
from typing import Optional

from .base import Transport

try:  # Optional dependency at runtime
    import serial  # type: ignore
    from serial import SerialException  # type: ignore
except Exception:  # pragma: no cover
    serial = None
    SerialException = Exception

import rclpy.logging
logger = rclpy.logging.get_logger("SerialTransport")

class SerialTransport(Transport):
    """
    PySerial transport that emits bytes for both control and publish streams.
    """

    def __init__(self, port: str, baud: int = 115200, timeout: float = 0.02):
        super().__init__()
        self.port = port
        self.baud = baud
        self.timeout = timeout
    # Keep serial.Serial out of type annotations to avoid import-time issues
        self._ser: Optional[object] = None
        self._reader: Optional[threading.Thread] = None
        self._writer: Optional[threading.Thread] = None
        self._wq: "queue.Queue[bytes]" = queue.Queue(maxsize=100)
        self._stop_evt = threading.Event()

    def start(self):
        with self._lock:
            if self._running:
                return
            if serial is None:
                self._emit_status(False, 'pyserial not installed')
                return

            try:
                self._ser = serial.Serial(self.port, self.baud, timeout=self.timeout)
            except Exception as e:  # SerialException or others
                self._emit_status(False, f'serial open failed: {e}')
                return

            self._stop_evt.clear()
            self._reader = threading.Thread(target=self._reader_loop, daemon=True)
            self._writer = threading.Thread(target=self._writer_loop, daemon=True)
            self._running = True
            self._reader.start()
            self._writer.start()
            self._emit_status(True, 'serial open')

    def stop(self):
        with self._lock:
            if not self._running:
                return
            self._running = False
            self._stop_evt.set()
            try:
                if self._ser is not None:
                    try:
                        self._ser.flush()
                    except Exception:
                        logger.error('Error flushing serial port')
                        pass
            finally:
                # Closing serial unblocks reader/writer
                try:
                    if self._ser is not None:
                        self._ser.close()
                except Exception:
                    logger.error('Error closing serial port')
                    pass
                self._ser = None
            self._emit_status(False, 'serial closed')

    def send(self, data: bytes):
        try:
            self._wq.put_nowait(bytes(data))
        except queue.Full:
            self._emit_status(True, 'tx queue full; dropping frame')

    # =========================================================
    # Threads
    # =========================================================
    def _reader_loop(self):
        ser = self._ser
        if ser is None:
            return
        # Read in chunks; framing is handled by the protocol layer
        while not self._stop_evt.is_set():
            try:
                chunk = ser.read(1024)  # up to 1KB per read
                if chunk:
                    self._emit_bytes(chunk)
                else:
                    # Avoid busy spin when the read times out
                    time.sleep(0.001)
            except SerialException as e:
                self._emit_status(False, f'serial read error: {e}')
                break
            except Exception:
                break

    def _writer_loop(self):
        ser = self._ser
        if ser is None:
            return
        while not self._stop_evt.is_set():
            try:
                data = self._wq.get(timeout=0.05)
            except queue.Empty:
                continue
            try:
                ser.write(data)
            except SerialException as e:
                self._emit_status(False, f'serial write error: {e}')
                break
            except Exception:
                break
