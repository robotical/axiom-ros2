"""One acknowledged control and acquisition session per Axiom board."""

import json
import math
import threading
import time
from urllib.parse import urlencode, urlsplit, urlunsplit

from .rpc import Requests, SessionError
from ..mini_hdlc import MiniHDLC
from ..protocols.overascii import Decoder as OverAsciiDecoder
from ..protocols.overascii import encode as overascii_encode
from ..protocols.ric_serial import RICSerial
from ..transports.serial import SerialTransport
from ..utils.string import find_json_fragments


def _is_device_publication(data):
    """Distinguish console status JSON from current or legacy device records."""
    if not isinstance(data, dict):
        return False
    # Keep unsupported versions visible to the pipeline's validation.
    if '_v' in data:
        return True
    return any(
        isinstance(devices, dict)
        and any(
            isinstance(packet, dict) and ('_i' in packet or '_t' in packet)
            for packet in devices.values()
        )
        for devices in data.values()
    )


class Session:
    def __init__(self, on_publish=None, on_state=None, on_error=None, on_console=None):
        self.on_publish = on_publish or (lambda data: None)
        self.on_state = on_state or (lambda ready, reason: None)
        self.on_error = on_error or (lambda reason: None)
        self.on_console = on_console or (lambda line: None)
        self.lock = threading.RLock()
        self.ascii_lock = threading.Lock()
        self.requests = Requests()
        self.connected = False
        self.transport_ready = False
        self.connecting = False
        self.generation = 0
        self.last_error = ''
        self.uri = ''
        self.firmware = {}
        self.socket = None
        self.serial = None
        self.thread = None
        self.opened = threading.Event()
        self.hdlc = MiniHDLC()
        self.ascii_pending = None
        self.console_buffer = bytearray()
        self.transport = 'ws'
        self.ws_mode = 'RICSerial'
        self.serial_mode = 'auto'

    def connect(
        self,
        uri,
        *,
        transport='ws',
        timeout=5.0,
        ws_mode='RICSerial',
        serial_mode='auto',
        baud=115200,
        serial_timeout=0.02,
    ):
        if transport not in ('ws', 'serial') or ws_mode not in ('RICSerial', 'RICFrame'):
            raise SessionError('Use serial or a framed RICSerial/RICFrame WebSocket')
        if serial_mode not in ('auto', 'overascii', 'ascii'):
            raise SessionError('Unknown serial mode')
        with self.lock:
            if self.connected:
                if uri != self.uri:
                    raise SessionError('Disconnect before selecting another board')
                return self.firmware
            if self.connecting:
                raise SessionError('Connection already in progress')
            self.connecting = True
        self.close('Starting connection', preserve_connecting=True)
        with self.lock:
            generation = self.generation
            self.transport, self.ws_mode, self.serial_mode = transport, ws_mode, serial_mode
            self.uri = uri
            self.last_error = ''
            self.opened = threading.Event()
            opened = self.opened
            parser = RICSerial(self.hdlc)
            parser.on_frame = lambda frame: self._frame(generation, frame)
            parser.on_error = self.on_error
            oa = OverAsciiDecoder()
            oa.on_binary = parser.feed_bytes
        socket = serial = None
        try:
            if transport == 'serial':
                serial = SerialTransport(uri, baud, serial_timeout)
                serial.on_bytes = lambda data: self._serial_bytes(generation, data, oa)
                serial.on_status = lambda ready, reason: self._status(generation, ready, reason)
                with self.lock:
                    if generation != self.generation:
                        raise SessionError('Connection cancelled')
                    self.serial = serial
                serial.start()
                if generation != self.generation:
                    serial.stop()
                    raise SessionError('Connection cancelled')
            else:
                import websocket

                parts = urlsplit(uri)
                if parts.scheme not in ('ws', 'wss') or not parts.hostname:
                    raise SessionError('Expected a ws:// or wss:// device URI')
                # Raw RICJSON does not return API replies in current firmware.
                if parts.path in ('', '/', '/devjson'):
                    parts = parts._replace(path='/ws')
                wire_uri = urlunsplit(parts)
                socket = websocket.WebSocketApp(
                    wire_uri,
                    on_open=lambda ws: self._ws_open(generation, ws),
                    on_close=lambda ws, code, reason: self._status(
                        generation, False, f'WebSocket closed: {code} {reason}'
                    ),
                    on_error=lambda ws, exc: self._status(generation, False, str(exc)),
                    on_message=lambda ws, msg: self._ws_message(generation, msg, parser),
                )
                thread = threading.Thread(target=socket.run_forever, name='axiom-ws', daemon=True)
                with self.lock:
                    if generation != self.generation:
                        raise SessionError('Connection cancelled')
                    self.socket, self.thread = socket, thread
                thread.start()
            if not opened.wait(timeout) or not self.transport_ready:
                raise SessionError(self.last_error or 'Transport connection timed out')
            firmware = self.request('v', timeout=timeout)
            with self.lock:
                if generation != self.generation or not self.transport_ready:
                    raise SessionError('Connection cancelled during handshake')
                self.firmware = firmware
                self.connected = True
                self.connecting = False
            self.on_state(True, 'Firmware handshake complete')
            return firmware
        except Exception as exc:
            # A cancelled connection must not close a newer caller's session.
            if generation == self.generation:
                self.close(str(exc))
            with self.lock:
                resource_is_current = (
                    self.socket is socket if transport == 'ws' else self.serial is serial
                )
                if resource_is_current:
                    self.connecting = False
            raise SessionError(str(exc)) from exc

    def close(self, reason='Disconnected', preserve_connecting=False):
        with self.lock:
            self.generation += 1
            self.connected = self.transport_ready = False
            self.firmware = {}
            if not preserve_connecting:
                self.connecting = False
            self.last_error = reason
            self.opened.set()
            self.requests.cancel_all(reason)
            self.ascii_pending = None
            self.console_buffer.clear()
            socket, self.socket = self.socket, None
            serial, self.serial = self.serial, None
            thread, self.thread = self.thread, None
        if socket:
            socket.close(timeout=0.5)
        if serial:
            serial.stop()
        if thread and thread is not threading.current_thread():
            thread.join(timeout=1.0)
        self.on_state(False, reason)

    def _ws_open(self, generation, socket):
        with self.lock:
            stale = generation != self.generation
            if not stale:
                self._status(generation, True, 'Transport open')
        if stale:
            socket.close(timeout=0.5)

    def _status(self, generation, ready, reason):
        with self.lock:
            if generation != self.generation:
                return
            self.transport_ready = ready
            if not ready:
                self.generation += 1
                self.connected = False
                self.last_error = reason
                self.requests.cancel_all(reason)
            self.opened.set()
        if not ready:
            self.on_state(False, reason)

    def _ws_message(self, generation, message, parser):
        if generation != self.generation:
            return
        if not isinstance(message, (bytes, bytearray)):
            self.on_error('Unexpected text on framed WebSocket')
            return
        if len(message) > 262144:
            self.on_error('WebSocket message exceeds receive limit')
            return
        if self.ws_mode == 'RICSerial':
            parser.feed_bytes(message)
        else:
            self._frame(generation, message)

    def _serial_bytes(self, generation, raw, oa):
        if generation != self.generation:
            return
        # OverAscii bytes always have their high bit set. Console text can be
        # interleaved, including between escaped bytes and across read chunks.
        oa.feed(bytes(b for b in raw if b & 0x80))
        low = bytes(b for b in raw if not b & 0x80)
        if low:
            self._console(generation, low)

    def _console(self, generation, raw):
        with self.lock:
            if generation != self.generation:
                return
            self.console_buffer.extend(raw)
            if len(self.console_buffer) > 65536:
                self.console_buffer.clear()
                self.on_error('Console receive buffer overflow')
                return
            text = self.console_buffer.decode('utf-8', errors='replace')
            fragments = find_json_fragments(text)
            end = 0
            for start, end in fragments:
                try:
                    data = json.loads(text[start:end])
                except ValueError:
                    continue
                pending = self.ascii_pending
                if (
                    pending
                    and isinstance(data, dict)
                    and 'rslt' in data
                    and str(data.get('req', '')).strip().split('?')[0] == pending[1].split('?')[0]
                ):
                    self.requests.resolve(pending[0], json.dumps(data).encode())
                elif isinstance(data, dict) and 'rslt' not in data:
                    if _is_device_publication(data):
                        self.on_publish(data)
                    else:
                        self.on_console(text[start:end])
            if end:
                self.console_buffer[:] = text[end:].encode()
            elif b'\n' in self.console_buffer and b'{' not in self.console_buffer:
                lines = bytes(self.console_buffer).split(b'\n')
                self.console_buffer[:] = lines.pop()
                for line in lines:
                    self.on_console(line.decode(errors='replace'))

    def _frame(self, generation, frame):
        # Keep checking the session and resolving a number atomic with close().
        with self.lock:
            self._frame_current(generation, frame)

    def _frame_current(self, generation, frame):
        if generation != self.generation or len(frame) < 2:
            return
        number, typeproto = frame[:2]
        message_type, protocol = typeproto >> 6, typeproto & 0x3F
        if message_type == 1 and protocol == 2 and len(frame) >= 3 and frame[2] == 1:
            self.requests.resolve(number, frame[3:].split(b'\0', 1)[0])
        elif message_type == 2:
            body = frame[3:] if protocol == 2 and len(frame) >= 3 and frame[2] == 1 else frame[2:]
            if protocol not in (0, 2, 0x3E):
                self.on_error(f'Unsupported publication protocol {protocol}')
                return
            try:
                self.on_publish(json.loads(body.rstrip(b'\0')))
            except (ValueError, UnicodeError) as exc:
                self.on_error(f'Invalid devjson publication: {exc}')
        elif protocol == 3:
            self.on_error(
                'Bridged RIC messages require a bridge-id envelope; '
                'unsupported on direct Axiom session'
            )

    def _exchange(self, body, element, timeout, ascii_path=None):
        if not math.isfinite(timeout) or not 0 < timeout <= 60:
            raise SessionError('RPC timeout must be between zero and 60 seconds')
        with self.lock:
            if not self.transport_ready:
                raise SessionError('Not connected')
            generation = self.generation
            number, item = self.requests.reserve()
        frame = bytes([number, 2, element]) + body + b'\0'

        def send():
            with self.lock:
                if generation != self.generation or not self.transport_ready:
                    raise SessionError('Session changed before send')
                socket, serial = self.socket, self.serial
                if ascii_path is not None:
                    self.ascii_pending = (number, ascii_path)
            if serial:
                payload = (
                    (ascii_path + '\n').encode()
                    if ascii_path is not None
                    else overascii_encode(self.hdlc.encode(frame))
                )
                serial.send(payload)
            elif socket:
                socket.send(
                    self.hdlc.encode(frame) if self.ws_mode == 'RICSerial' else frame, opcode=2
                )
            else:
                raise SessionError('Transport unavailable')

        try:
            payload = self.requests.finish(number, item, timeout, send)
            result = json.loads(payload)
            if not isinstance(result, dict):
                raise SessionError('Firmware response is not an object')
            if result.get('rslt') not in ('ok', 'success'):
                raise SessionError(f'Firmware rejected request: {result}')
            return result
        except OSError as exc:
            self.close(f'Transport send failed: {exc}')
            raise SessionError(str(exc)) from exc
        except ValueError as exc:
            raise SessionError(str(exc)) from exc
        finally:
            with self.lock:
                if self.ascii_pending and self.ascii_pending[0] == number:
                    self.ascii_pending = None

    def request(self, path, timeout=3.0):
        path = path.strip().lstrip('/')
        if not path or '\n' in path or '\r' in path or '\0' in path:
            raise SessionError('Invalid REST URL')
        if self.transport == 'serial' and self.serial_mode == 'ascii':
            if not self.ascii_lock.acquire(timeout=timeout):
                raise SessionError('ASCII request channel busy')
            try:
                return self._exchange(path.encode(), 0, timeout, ascii_path=path)
            except SessionError:
                # Unnumbered late replies cannot be safely matched after a timeout.
                self.close('ASCII request failed; reconnect to reset response stream')
                raise
            finally:
                self.ascii_lock.release()
        return self._exchange(path.encode(), 0, timeout)

    def command(self, endpoint, timeout=3.0, **fields):
        if self.transport == 'serial' and self.serial_mode == 'ascii':
            encoded = {
                k: json.dumps(v, separators=(',', ':')) if isinstance(v, (dict, list)) else v
                for k, v in fields.items()
            }
            return self.request(endpoint + '?' + urlencode(encoded), timeout)
        return self._exchange(
            json.dumps(dict(cmdName=endpoint, **fields), separators=(',', ':')).encode(),
            3,
            timeout,
        )

    def subscribe(self, rate_hz, trigger='time', timeout=3.0):
        if not math.isfinite(rate_hz) or rate_hz < 0 or rate_hz > 1000:
            raise SessionError('Publication rate must be between 0 and 1000 Hz')
        if trigger not in ('time', 'change', 'timeorchange'):
            raise SessionError('Invalid subscription trigger')
        if rate_hz == 0:
            return self.command('subscription', timeout, action='unsubscribe', name='devjson')
        response = self.command(
            'subscription',
            timeout,
            action='update',
            pubRecs=[{'name': 'devjson', 'rateHz': rate_hz, 'trigger': trigger}],
        )
        if not any(t.get('name') == 'devjson' for t in response.get('topics', [])):
            raise SessionError('Firmware did not acknowledge the devjson topic')
        return response

    def ping(self, payload_size=0, timeout=3.0):
        if not 0 <= payload_size <= 65536:
            raise SessionError('Ping payload_size must be 0..65536')
        start = time.monotonic()
        self.request('v' + ('?pad=' + 'x' * payload_size if payload_size else ''), timeout)
        return (time.monotonic() - start) * 1000
