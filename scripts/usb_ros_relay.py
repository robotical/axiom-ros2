#!/usr/bin/env python3
"""Relay one Mac USB client to ROS's RICSerial WebSocket transport.

No sensor decoding or independent subscription happens here. The ROS driver owns
all requests. Only OverAscii is translated; framed bytes retain firmware CRCs.
"""

import argparse
import asyncio
from pathlib import Path
import signal
import sys

import serial
import websockets

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src' / 'axiom_driver'))
from axiom_driver.protocols.overascii import Decoder, encode  # noqa: E402


class Relay:
    """Allow only one acquisition owner and release the port on disconnect."""

    def __init__(self, port, baud):
        self.port, self.baud = port, baud
        self.busy = False

    async def handle(self, websocket, path=None):
        if self.busy:
            await websocket.close(1013, 'A ROS driver already owns this USB link')
            return
        self.busy = True
        usb = None
        tasks = []
        try:
            usb = serial.Serial(self.port, self.baud, timeout=0.02, write_timeout=1)
            print(f'USB connected: {self.port}', flush=True)
            decoder = Decoder()
            decoded = bytearray()
            decoder.on_binary = decoded.extend

            async def from_usb():
                while True:
                    raw = await asyncio.to_thread(usb.read, max(1, min(usb.in_waiting, 65536)))
                    # Low-bit console bytes can occur between escape bytes.
                    decoder.feed(bytes(b for b in raw if b & 0x80))
                    if decoded:
                        await websocket.send(bytes(decoded))
                        decoded.clear()

            async def to_usb():
                async for message in websocket:
                    if not isinstance(message, bytes):
                        await websocket.close(1003, 'Binary RICSerial required')
                        return
                    await asyncio.to_thread(usb.write, encode(message))

            tasks = [asyncio.create_task(from_usb()), asyncio.create_task(to_usb())]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except (OSError, websockets.ConnectionClosed) as exc:
            print(f'USB session ended: {exc}', flush=True)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            if usb:
                usb.close()
            self.busy = False
            await websocket.close()
            print('USB released', flush=True)


async def run(args):
    relay = Relay(args.port, args.baud)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    async with websockets.serve(relay.handle, args.host, args.listen_port, max_size=262144):
        print(f'Relay ready: ws://{args.host}:{args.listen_port}/ws', flush=True)
        await stop.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--baud', type=int, default=115200)
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--listen-port', type=int, default=8765)
    asyncio.run(run(parser.parse_args()))
