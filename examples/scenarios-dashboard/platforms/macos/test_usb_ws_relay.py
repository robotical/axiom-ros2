"""Exercise the physical relay with independent WebSocket and serial endpoints."""

import asyncio
import queue
import time
from types import SimpleNamespace

import pytest
import websockets

import usb_ws_relay as relay


class SerialPeer:
    def __init__(self, **kwargs):
        self.input = queue.Queue()
        self.writes = []
        self.unplugged = False
        self.closed = False

    def open(self):
        pass

    @property
    def in_waiting(self):
        if self.unplugged:
            raise OSError('USB unplugged')
        return 1

    def read(self, size):
        try:
            return self.input.get(timeout=.02)
        except queue.Empty:
            return b''

    def write(self, payload):
        self.writes.append(payload)
        return len(payload)

    def close(self):
        self.closed = True


def test_usb_absence_replug_port_change_and_single_owner(monkeypatch):
    ports, sessions = [], []
    monkeypatch.setattr(relay.list_ports, 'comports', lambda: ports)
    def serial_peer(**kwargs):
        peer = SerialPeer(**kwargs)
        sessions.append(peer)
        return peer
    monkeypatch.setattr(relay.serial, 'Serial', serial_peer)

    async def check():
        bridge = relay.MartyRelay()
        server = await asyncio.start_server(bridge.handle, '127.0.0.1', 0)
        uri = f'ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/ws'
        async with server:
            with pytest.raises(websockets.InvalidMessage):
                async with websockets.connect(uri):
                    pass
            assert not bridge.busy and not sessions
            ports.append(SimpleNamespace(device='/usb/first', vid=0x1A86, pid=0x7523))
            async with websockets.connect(uri) as client:
                assert sessions[-1].port == '/usb/first'
                with pytest.raises(websockets.InvalidStatus):
                    async with websockets.connect(uri):
                        pass
                assert len(sessions) == 1 and bridge.busy
                payload = bytes(range(256))
                await client.send(payload)
                deadline = time.monotonic() + 1
                while not sessions[-1].writes and time.monotonic() < deadline:
                    await asyncio.sleep(.01)
                assert sessions[-1].writes == [relay.encode(payload)]
                # Console logging interleaved with escaped firmware bytes must
                # never leak into the ROS/MartyPy binary stream.
                encoded = relay.encode(payload)
                sessions[-1].input.put(b'console\n' + encoded[:1])
                sessions[-1].input.put(b'log\n' + encoded[1:])
                received = b''
                while len(received) < len(payload):
                    received += await asyncio.wait_for(client.recv(), 1)
                assert received == payload
                sessions[-1].unplugged = True
                with pytest.raises(websockets.ConnectionClosed):
                    await asyncio.wait_for(client.recv(), 1)
            assert sessions[-1].closed and not bridge.busy
            ports[0].device = '/usb/replugged'
            async with websockets.connect(uri) as client:
                assert len(sessions) == 2 and sessions[-1].port == '/usb/replugged'
                await bridge.close()
                with pytest.raises(websockets.ConnectionClosed):
                    await asyncio.wait_for(client.recv(), 1)
            await asyncio.sleep(.1)
            assert sessions[-1].closed and not bridge.busy
    asyncio.run(check())


def test_usb_discovery_refuses_ambiguous_devices(monkeypatch):
    ports = [SimpleNamespace(device=f'/usb/{i}', vid=0x303A, pid=0x1001) for i in range(2)]
    monkeypatch.setattr(relay.list_ports, 'comports', lambda: ports)
    with pytest.raises(OSError, match='Multiple Axiom'):
        relay.resolve_port('axiom')
    assert relay.resolve_port('axiom', '/chosen/port') == '/chosen/port'


def test_martypy_historical_handshake(monkeypatch):
    monkeypatch.setattr(relay, 'resolve_port', lambda *args: '/usb/marty')
    monkeypatch.setattr(relay.serial, 'Serial', SerialPeer)
    async def check():
        bridge = relay.MartyRelay()
        server = await asyncio.start_server(bridge.handle, '127.0.0.1', 0)
        async with server:
            reader, writer = await asyncio.open_connection('127.0.0.1',
                                                            server.sockets[0].getsockname()[1])
            writer.write(b'GET /ws HTTP/1.1\r\nConnection: upgrade\r\nUpgrade: websocket\r\n\r\n')
            await writer.drain()
            response = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 1)
            assert response.startswith(b'HTTP/1.1 101') and b'Sec-WebSocket-Accept:' in response
            writer.close()
            await writer.wait_closed()
            await asyncio.sleep(.1)
            assert not bridge.busy
    asyncio.run(check())
