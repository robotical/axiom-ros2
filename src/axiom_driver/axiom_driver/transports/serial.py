"""PySerial transport with bounded writes and prompt cancellation."""

import threading


class SerialTransport:
    def __init__(self, port, baud=115200, timeout=0.02):
        self.port, self.baud, self.timeout = port, baud, timeout
        self.on_status = None
        self.on_bytes = None
        self._ser = None
        self._reader = None
        self._stop = threading.Event()
        self._write_lock = threading.Lock()

    def start(self):
        import serial

        if self._ser is not None:
            raise RuntimeError('Serial transport already open')
        self._ser = serial.Serial(self.port, self.baud, timeout=self.timeout, write_timeout=1.0)
        self._stop.clear()
        self._reader = threading.Thread(target=self._read, name='axiom-serial', daemon=True)
        if self.on_status:
            self.on_status(True, 'Serial open')
        self._reader.start()
        return True

    def stop(self):
        self._stop.set()
        ser, self._ser = self._ser, None
        if ser:
            ser.close()  # Unblocks reads; do not flush a stalled device at shutdown.
        if self._reader and self._reader is not threading.current_thread():
            self._reader.join(timeout=1.1)

    def send(self, data):
        with self._write_lock:
            ser = self._ser
            if ser is None or self._stop.is_set():
                raise ConnectionError('Serial port closed')
            if ser.write(data) != len(data):
                raise ConnectionError('Incomplete serial write')

    def _read(self):
        ser = self._ser
        while not self._stop.is_set():
            try:
                data = ser.read(4096)
                if data and self.on_bytes:
                    self.on_bytes(data)
            except Exception as exc:
                if not self._stop.is_set():
                    self._stop.set()
                    if self.on_status:
                        self.on_status(False, str(exc))
                break
