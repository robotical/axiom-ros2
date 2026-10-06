"""Protocol and real WebSocket regressions without a ROS dependency."""

import asyncio
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time

from axiom_driver.core.rpc import Requests, SessionError
from axiom_driver.core.session import Session
from axiom_driver.mini_hdlc import crc16_ccitt, MiniHDLC
from axiom_driver.protocols.overascii import Decoder, encode
from axiom_driver.protocols.ric_serial import RICSerial
import pytest
import websockets


class FirmwareServer:
    """A real socket peer implementing firmware's numbered RICREST contract."""

    def __init__(self):
        self.hdlc = MiniHDLC()
        self.paths = []
        self.commands = []
        self.connections = set()
        self.ready = threading.Event()
        self.respond = True
        self.drop_on_request = False
        self.callback = None
        self.thread = threading.Thread(target=self.run, daemon=True)
        self.thread.start()
        assert self.ready.wait(5)

    def run(self):
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)

        async def start():
            self.server = await websockets.serve(self.handle, '127.0.0.1', 0, close_timeout=0.2)
            self.port = self.server.sockets[0].getsockname()[1]
            self.ready.set()

        self.loop.run_until_complete(start())
        self.loop.run_forever()
        self.loop.close()

    async def handle(self, socket, path=None):
        self.connections.add(socket)
        try:
            async for message in socket:
                ok, frame = self.hdlc.try_decode(message)
                assert ok and frame[1] == 2
                if self.drop_on_request:
                    await socket.close()
                    break
                if not self.respond:
                    continue
                if frame[2] == 0:
                    request = frame[3:].rstrip(b'\0').decode()
                    self.paths.append(request)
                    response = {'rslt': 'ok', 'req': request, 'version': 'test-fw'}
                else:
                    request = json.loads(frame[3:].rstrip(b'\0'))
                    self.commands.append(request)
                    response = {
                        'rslt': 'ok',
                        'req': request['cmdName'],
                        'topics': [{'name': 'devjson', 'idx': 0}],
                    }
                if self.callback:
                    response = self.callback(request, response)
                if response is not None:
                    await socket.send(
                        self.hdlc.encode(
                            bytes([frame[0], 0x42, 1]) + json.dumps(response).encode()
                        )
                    )
        finally:
            self.connections.discard(socket)

    def publish(self, data):
        async def send():
            for connection in list(self.connections):
                await connection.send(self.hdlc.encode(b'\0\x80' + json.dumps(data).encode()))

        asyncio.run_coroutine_threadsafe(send(), self.loop).result(3)

    def disconnect_clients(self):
        async def disconnect():
            for connection in list(self.connections):
                await connection.close()

        asyncio.run_coroutine_threadsafe(disconnect(), self.loop).result(3)

    def close(self):
        async def shutdown():
            self.server.close()
            await self.server.wait_closed()

        asyncio.run_coroutine_threadsafe(shutdown(), self.loop).result(3)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(3)

    @property
    def uri(self):
        return f'ws://127.0.0.1:{self.port}/ws'


@pytest.fixture
def firmware():
    peer = FirmwareServer()
    yield peer
    peer.close()


def test_streaming_hdlc_fragments_shared_delimiter_and_crc():
    assert crc16_ccitt(b'123456789') == 0x29B1
    codec = MiniHDLC()
    parser = RICSerial(codec)
    frames, errors = [], []
    parser.on_frame, parser.on_error = frames.append, errors.append
    one = codec.encode(bytes(range(256)))
    two = codec.encode(b'second')
    for byte in one + two[1:]:
        parser.feed_bytes(bytes([byte]))
    assert frames == [bytes(range(256)), b'second']
    broken = bytearray(two)
    broken[1] ^= 1
    parser.feed_bytes(broken)
    assert errors and len(frames) == 2


def test_overascii_all_bytes_and_interleaved_console():
    decoded = bytearray()
    decoder = Decoder()
    decoder.on_binary = decoded.extend
    for byte in encode(bytes(range(256))):
        decoder.feed(bytes([byte]))
    assert decoded == bytes(range(256))
    session = Session()
    session.generation = 1
    codec = MiniHDLC()
    parser = RICSerial(codec)
    frames = []
    parser.on_frame = frames.append
    oa = Decoder()
    oa.on_binary = parser.feed_bytes
    for byte in encode(codec.encode(b'body')):
        session._serial_bytes(1, b'console\n' + bytes([byte]), oa)
    assert frames == [b'body']


def test_rpc_capacity_cancellation_and_send_failure():
    requests = Requests()
    all_requests = [requests.reserve() for _ in range(255)]
    assert len({n for n, _ in all_requests}) == 255
    with pytest.raises(SessionError, match='in use'):
        requests.reserve()
    requests.cancel_all('Disconnected')
    number, pending = all_requests[0]
    with pytest.raises(SessionError, match='Disconnected'):
        requests.finish(number, pending, 0.1, lambda: None)
    number, pending = requests.reserve()
    with pytest.raises(OSError):
        requests.finish(
            number, pending, 0.1, lambda: (_ for _ in ()).throw(OSError('send failed'))
        )
    assert number not in requests.pending


def test_websocket_ack_subscription_publication_and_real_rtt(firmware):
    received = []
    session = Session(on_publish=received.append)
    try:
        session.connect(firmware.uri.replace('/ws', '/devjson'))
        assert session.connected
        session.subscribe(10)
        assert firmware.commands[-1]['pubRecs'][0]['trigger'] == 'time'
        session.subscribe(0)
        assert firmware.commands[-1]['action'] == 'unsubscribe'
        firmware.publish({'_v': 1, '_t': 0, '1': {'38': {'_i': 1, '_o': 1, 'x': '006400'}}})
        deadline = time.monotonic() + 2
        while not received and time.monotonic() < deadline:
            time.sleep(0.005)
        assert received[0]['1']['38']['_i'] == 1
        assert 0 <= session.ping(10) < 2000
        assert firmware.paths[-1] == 'v?pad=xxxxxxxxxx'
    finally:
        session.close()


def test_concurrent_rpc_responses_and_disconnect_cancellation(firmware):
    session = Session()
    try:
        session.connect(firmware.uri)
        with ThreadPoolExecutor(max_workers=4) as executor:
            results = list(executor.map(lambda n: session.request(f'v?test={n}'), range(20)))
            assert [r['req'] for r in results] == [f'v?test={n}' for n in range(20)]
            firmware.respond = False
            waiting = executor.submit(session.request, 'slow', 20)
            deadline = time.monotonic() + 2
            while not session.requests.pending and time.monotonic() < deadline:
                time.sleep(0.005)
            start = time.monotonic()
            session.close()
            with pytest.raises(SessionError):
                waiting.result(2)
            assert time.monotonic() - start < 2
            assert not session.requests.pending
    finally:
        session.close()


def test_server_close_clears_ready_and_cancels_request(firmware):
    session = Session()
    try:
        session.connect(firmware.uri)
        firmware.drop_on_request = True
        with pytest.raises(SessionError):
            session.request('v', timeout=3)
        assert not session.connected and not session.transport_ready
    finally:
        session.close()


def test_rejected_subscription_is_not_success(firmware):
    session = Session()
    try:
        session.connect(firmware.uri)
        firmware.callback = lambda request, response: {'rslt': 'ok', 'topics': []}
        with pytest.raises(SessionError, match='acknowledge'):
            session.subscribe(10)
    finally:
        session.close()


def test_stale_generation_cannot_fulfill_new_request():
    session = Session()
    session.generation = 2
    number, pending = session.requests.reserve()
    session._frame(1, bytes([number, 0x42, 1]) + b'{"rslt":"ok"}')
    assert not pending.event.is_set()
    session._frame(2, bytes([number, 0x42, 1]) + b'{"rslt":"ok"}')
    assert pending.event.is_set()


def test_ascii_telemetry_does_not_fulfill_rpc():
    session = Session()
    number, pending = session.requests.reserve()
    session.ascii_pending = (number, 'devman/typeinfo?bus=1&addr=0x38')
    session._console(0, b'{"1":{"38":{"_i":1,"x":"006400"}}}')
    assert not pending.event.is_set()
    session._console(0, b'{"req":"v","rslt":"ok"}')
    assert not pending.event.is_set()
    session._console(0, b'{"req":"devman/typeinfo?bus=1&addr=0x38","rslt":"ok"}')
    assert pending.event.is_set()


def test_console_status_stays_separate_from_device_publications():
    publications, console = [], []
    session = Session(on_publish=publications.append, on_console=console.append)
    status = {'NetMan': {'wifiSTA': {'connected': True}}, 'SysMan': {'avgUs': 15}}
    current = {'_v': 1, '0': {'1': {'_t': 'AxiomPowerV1', 'x': '006400'}}}
    legacy = {'I2C': {'38': {'_t': 'AHT20', 'x': '006400'}}}
    unsupported = {'_v': 2}
    number, pending = session.requests.reserve()
    session.ascii_pending = (number, 'v')
    stream = '\n'.join(json.dumps(data) for data in (status, current, legacy, unsupported))
    # Console fragments can cross serial reads.
    for offset in range(0, len(stream), 7):
        session._console(0, stream[offset: offset + 7].encode())
    assert [json.loads(line) for line in console] == [status]
    assert publications == [current, legacy, unsupported]
    assert not pending.event.is_set()
