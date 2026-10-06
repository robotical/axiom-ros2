"""Exercise PySerial on a real pseudo-terminal with firmware framing."""

import json
import os
import select
import threading

import pytest

pytest.importorskip('serial')

from axiom_driver.core.rpc import SessionError  # noqa: E402,I100
from axiom_driver.core.session import Session  # noqa: E402
from axiom_driver.mini_hdlc import MiniHDLC  # noqa: E402
from axiom_driver.protocols.overascii import Decoder, encode  # noqa: E402
from axiom_driver.protocols.ric_serial import RICSerial  # noqa: E402


class SerialFirmware:
    def __init__(self, ascii_mode=False):
        self.master, self.slave = os.openpty()
        self.path = os.ttyname(self.slave)
        self.stop = threading.Event()
        self.ascii_mode = ascii_mode
        self.hdlc = MiniHDLC()
        self.parser = RICSerial(self.hdlc)
        self.parser.on_frame = self.frame
        self.oa = Decoder()
        self.oa.on_binary = self.parser.feed_bytes
        self.buffer = bytearray()
        self.commands = []
        self.thread = threading.Thread(target=self.read, daemon=True)
        self.thread.start()

    def read(self):
        while not self.stop.is_set():
            ready, _, _ = select.select([self.master], [], [], 0.05)
            if ready:
                try:
                    data = os.read(self.master, 4096)
                except OSError:
                    return
                if self.ascii_mode:
                    self.buffer.extend(data)
                    while b'\n' in self.buffer:
                        line, _, remainder = self.buffer.partition(b'\n')
                        self.buffer[:] = remainder
                        if line:
                            self.reply(0, line.decode())
                else:
                    self.oa.feed(data)

    def frame(self, frame):
        request = frame[3:].rstrip(b'\0')
        request = json.loads(request) if frame[2] == 3 else request.decode()
        self.reply(frame[0], request)

    def reply(self, number, request):
        self.commands.append(request)
        response = {
            'rslt': 'ok',
            'req': request if isinstance(request, str) else request['cmdName'],
            'topics': [{'name': 'devjson', 'idx': 0}],
        }
        body = json.dumps(response).encode()
        if self.ascii_mode:
            os.write(self.master, body + b'\n')
        else:
            wire = encode(self.hdlc.encode(bytes([number, 0x42, 1]) + body))
            for start in range(0, len(wire), 3):
                os.write(self.master, wire[start: start + 3])

    def close(self):
        self.stop.set()
        self.thread.join(1)
        os.close(self.master)
        os.close(self.slave)


@pytest.mark.parametrize('mode', ['auto', 'overascii', 'ascii'])
def test_serial_handshake_rpc_and_subscription(mode):
    peer = SerialFirmware(ascii_mode=mode == 'ascii')
    session = Session()
    try:
        session.connect(peer.path, transport='serial', serial_mode=mode)
        assert session.connected
        session.subscribe(10)
        assert len(peer.commands) == 2
        assert session.ping() >= 0
        session.close()
        assert not session.connected
        assert session.serial is None
    finally:
        session.close()
        peer.close()


def test_failed_serial_open_never_reports_connected():
    session = Session()
    with pytest.raises(SessionError):
        session.connect('/nonexistent/axiom-test-port', transport='serial', timeout=0.2)
    assert not session.connected and not session.transport_ready
    assert session.serial is None
