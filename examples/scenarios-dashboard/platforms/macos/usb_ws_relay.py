"""Loopback USB relays that stay available while devices are unplugged.

Resolve the USB port for every driver session so replugging at a new port works.
The drivers own subscriptions and reconnects; this only forwards firmware bytes.
"""

import argparse
import asyncio
import base64
import hashlib
import os
from pathlib import Path
import signal
import struct
import sys

import serial
from serial.tools import list_ports
import websockets

USB_IDS = {'axiom': (0x303A, 0x1001), 'marty': (0x1A86, 0x7523)}
AXIOM_ROOT = Path(os.environ.get('AXIOM_ROS_ROOT',
                                Path(__file__).resolve().parents[4]))
sys.path.insert(0, str(AXIOM_ROOT / 'src' / 'axiom_driver'))
from axiom_driver.protocols.overascii import Decoder, encode  # noqa: E402


def resolve_port(kind, explicit=None):
    if explicit:
        return explicit
    matches = [p.device for p in list_ports.comports()
               if (p.vid, p.pid) == USB_IDS[kind]]
    if not matches:
        raise OSError(f'{kind.title()} USB disconnected')
    if len(matches) != 1:
        raise OSError(f'Multiple {kind.title()} devices; specify --{kind}-port')
    return matches[0]


async def send_frame(writer, payload, opcode=2):
    size = len(payload)
    header = bytes([0x80 | opcode, size]) if size < 126 else (
        bytes([0x80 | opcode, 126]) + struct.pack('>H', size) if size < 65536 else
        bytes([0x80 | opcode, 127]) + struct.pack('>Q', size))
    writer.write(header + payload)
    await writer.drain()


async def read_frame(reader):
    header = await reader.readexactly(2)
    if header[0] & 0x70 or not header[0] & 0x80:
        raise ValueError('Unfragmented firmware frames required')
    opcode, size = header[0] & 15, header[1] & 127
    if size == 126:
        size = struct.unpack('>H', await reader.readexactly(2))[0]
    elif size == 127:
        size = struct.unpack('>Q', await reader.readexactly(8))[0]
    if size > 262144 or (opcode >= 8 and size > 125):
        raise ValueError('Firmware frame too large')
    mask = await reader.readexactly(4) if header[1] & 128 else None
    payload = await reader.readexactly(size)
    if mask:
        payload = bytes(v ^ mask[i % 4] for i, v in enumerate(payload))
    return opcode, payload


class MartyRelay:
    def __init__(self, port=None):
        self.port = port
        self.busy = False
        self.connections = set()

    async def close(self):
        writers = list(self.connections)
        for writer in writers:
            writer.close()
        await asyncio.gather(*(writer.wait_closed() for writer in writers),
                             return_exceptions=True)

    async def handle(self, reader, writer):
        usb, tasks, acquired = None, [], False
        self.connections.add(writer)
        try:
            request = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 3)
            lines = request.decode('ascii').split('\r\n')
            headers = {key.lower(): value for key, value in
                       (line.split(':', 1) for line in lines[1:] if ':' in line)}
            if lines[0] != 'GET /ws HTTP/1.1' or headers.get('upgrade', '').strip() != 'websocket':
                raise ValueError('Firmware WebSocket required')
            if self.busy:
                writer.write(b'HTTP/1.1 503 USB link busy\r\nContent-Length: 0\r\n\r\n')
                await writer.drain()
                return
            self.busy, acquired = True, True
            port = resolve_port('marty', self.port)
            usb = serial.Serial(port=None, baudrate=115200, timeout=.02, write_timeout=1)
            usb.rts = usb.dtr = False
            usb.port = port
            usb.open()
            # MartyPy's historical firmware client omits Sec-WebSocket-Key.
            # Support that client as well as the standard handshake on loopback.
            key = headers.get('sec-websocket-key', '').strip()
            accept = base64.b64encode(hashlib.sha1(
                (key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest())
            writer.write(b'HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n'
                         b'Connection: Upgrade\r\nSec-WebSocket-Accept: ' + accept + b'\r\n\r\n')
            await writer.drain()
            print(f'Marty USB connected: {port}', flush=True)
            decoder, decoded = Decoder(), bytearray()
            decoder.on_binary = decoded.extend

            async def from_usb():
                while True:
                    data = await asyncio.to_thread(usb.read, max(1, min(usb.in_waiting, 65536)))
                    decoder.feed(bytes(b for b in data if b & 0x80))
                    if decoded:
                        await send_frame(writer, bytes(decoded))
                        decoded.clear()

            async def to_usb():
                while True:
                    opcode, payload = await read_frame(reader)
                    if opcode == 8:
                        return
                    if opcode == 9:
                        await send_frame(writer, payload, 10)
                    elif opcode == 2:
                        encoded = encode(payload)
                        written = await asyncio.to_thread(usb.write, encoded)
                        if written != len(encoded):
                            raise OSError('Incomplete USB write')
                    elif opcode != 10:
                        raise ValueError('Binary firmware frames required')

            tasks = [asyncio.create_task(from_usb()), asyncio.create_task(to_usb())]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (OSError, ValueError, TimeoutError, asyncio.IncompleteReadError,
                asyncio.LimitOverrunError) as exc:
            print(f'Marty session ended: {exc}', flush=True)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if usb:
                usb.close()
            if acquired:
                self.busy = False
            writer.close()
            await asyncio.gather(writer.wait_closed(), return_exceptions=True)
            self.connections.discard(writer)


async def serve(args):
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    if args.kind == 'axiom':
        sys.path.insert(0, str(AXIOM_ROOT / 'scripts'))
        from usb_ros_relay import Relay

        class AutoRelay(Relay):
            async def handle(self, websocket, path=None):
                if not self.busy:
                    try:
                        self.port = resolve_port('axiom', args.port)
                    except OSError as exc:
                        await websocket.close(1013, str(exc))
                        return
                await super().handle(websocket, path)

        server = await websockets.serve(AutoRelay(None, 115200).handle, '127.0.0.1',
                                        args.listen_port, max_size=262144)
    else:
        relay = MartyRelay(args.port)
        server = await asyncio.start_server(relay.handle, '127.0.0.1',
                                            args.listen_port, limit=8192)
    print(f'{args.kind.title()} relay listening on {args.listen_port}; waiting for USB', flush=True)
    async with server:
        await stop.wait()
        if args.kind == 'marty':
            await relay.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kind', required=True, choices=['axiom', 'marty'])
    parser.add_argument('--port')
    parser.add_argument('--listen-port', type=int, required=True)
    asyncio.run(serve(parser.parse_args()))
