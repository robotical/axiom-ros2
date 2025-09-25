# axiom_driver/axiom_bridge_node.py

import time
import threading
import json
from typing import Dict, Optional

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException

from axiom_driver.ric_consts import (
    TYPE_COMMAND, TYPE_RESPONSE,
    PROTO_RICREST, PROTO_BRIDGE_RICREST,
    ELEM_URL, ELEM_CMDRESPJSON,
    pack_type_proto,
)
from axiom_driver.mini_hdlc import MiniHDLC, FLAG_DEFAULT, ESC_DEFAULT, XOR_DEFAULT
from axiom_driver.sensors.registry import get_decoder
from axiom_driver.publisher_cache import PublisherCache
from axiom_driver.protocols.dispatcher import Dispatcher
from axiom_driver.protocols.ric_frame import RICFrame
from axiom_driver.protocols.ric_serial import RICSerial
from axiom_driver.transports.serial import SerialTransport
from axiom_driver.protocols.overascii import Decoder as OverAsciiDecoder, encode as overascii_encode

from axiom_driver.ric_consts import TYPE_PUBLISH, PROTO_RAWCMDFRAME

from axiom_interfaces.srv import (
    Connect, Disconnect, Ping, GetConnectionState, RicRestUrl
)

# Optional runtime dependency
try:
    import websocket  # type: ignore
except ImportError:  # pragma: no cover
    websocket = None


# ---------------------------- Connection state ----------------------------

class ConnectionState:
    def __init__(self):
        self.connected: bool = False
        self.uri: str = ''
        self.last_error: str = ''

        # WS data (sensor JSON via /devjson)
        self.data_ws: Optional[object] = None
        self.data_thread: Optional[threading.Thread] = None

        # WS control (RIC/REST via /ws)
        self.ctrl_ws: Optional[object] = None
        self.ctrl_thread: Optional[threading.Thread] = None

        # handshake for WS connect
        self._opened_event = threading.Event()
        self._error_event = threading.Event()

        # serial
        self.serial_transport: Optional[SerialTransport] = None


# ---------------------------- Main node ----------------------------

class AxiomBridgeNode(Node):
    def __init__(self):
        super().__init__('axiom_bridge_node')

        # ===== Parameters =====
        # Core
        self.declare_parameter('transport', 'ws')            # 'ws' | 'serial' | 'ble'(future)
        self.declare_parameter('device_uri', 'ws://')        # e.g. ws://192.168.1.7/devjson
        self.declare_parameter('auto_connect', False)
        self.declare_parameter('frame_id', 'axiom_link')

        # WS control channel
        self.declare_parameter('use_dual_ws', True)
        self.declare_parameter('ws_path', '/ws')             # control WS path if control_uri not set
        self.declare_parameter('control_uri', '')            # optional absolute control ws uri
        self.declare_parameter('ws_pcol', 'RICSerial')       # RICSerial | RICFrame | RICJSON
        self.declare_parameter('ricrest_proto', 'RICREST')   # RICREST | BRIDGE_RICREST

        # RPC / HDLC
        self.declare_parameter('rpc_default_timeout', 3.0)
        self.declare_parameter('hdlc_flag', FLAG_DEFAULT)
        self.declare_parameter('hdlc_escape', ESC_DEFAULT)
        self.declare_parameter('hdlc_xor', XOR_DEFAULT)

        # Serial params
        self.declare_parameter('serial.port', '/dev/ttyUSB0')
        self.declare_parameter('serial.baud', 115200)
        self.declare_parameter('serial.timeout', 0.02)
        # Serial mode:
        #   'auto'      → detect OverAscii vs ASCII by inbound stream
        #   'overascii' → use OverAscii+HDLC (RICSerial tunneled)
        #   'ascii'     → send "url\n" and parse console JSON
        self.declare_parameter('serial.mode', 'auto')

        # Debug
        self.declare_parameter('debug_hex', True)

        # ===== Members =====
        self.state = ConnectionState()
        self.publisher_cache = PublisherCache(self)

        # RIC/REST tracking (WS code path)
        self._ric_msgnum = 1
        self._ric_lock = threading.Lock()
        self._ric_wait: Dict[int, threading.Event] = {}
        self._ric_resp: Dict[int, bytes] = {}

        # HDLC (MiniHDLC) for both WS(RICSerial) and serial (inner framing)
        self._mini_hdlc = MiniHDLC(
            self.get_parameter('hdlc_flag').value,
            self.get_parameter('hdlc_escape').value,
            self.get_parameter('hdlc_xor').value,
        )

        # Dispatcher (matches responses by msgnum, can handle publish later)
        self._dispatcher = Dispatcher()

        # RICSerial (HDLC deframer for inner RIC frames)
        self._ric_serial = RICSerial(self._mini_hdlc)
        self._ric_serial.on_frame = self._on_serial_frame
        self._ric_serial.on_error = lambda m: self.get_logger().warn(f'RICSerial: {m}')

    # Forward non-response frames to a publish handler
        self._dispatcher.on_publish = self._handle_publish_frame

        # Serial mode helpers
        self._serial_mode = str(self.get_parameter('serial.mode').value or 'auto')
        self._oa = OverAsciiDecoder()
        self._oa.on_binary = self._ric_serial.feed_bytes         # OverAscii → HDLC layer
        self._console_buf = bytearray()                          # for ASCII console JSON
        self._console_wait_ev: Optional[threading.Event] = None  # url → event
        self._console_resp_buf: Optional[bytes] = None           # url → bytes
        self._serial_debug = bool(self.get_parameter('debug_hex').value)

        # ===== Services =====
        self.create_service(Connect, 'connect', self.handle_connect)
        self.create_service(Disconnect, 'disconnect', self.handle_disconnect)
        self.create_service(Ping, 'ping', self.handle_ping)
        self.create_service(GetConnectionState, 'get_connection_state', self.handle_get_state)
        self.create_service(RicRestUrl, 'ric_rest_url', self.handle_ric_rest_url)

        # ===== Autoconnect =====
        if self.get_parameter('auto_connect').get_parameter_value().bool_value:
            transport = self.get_parameter('transport').get_parameter_value().string_value
            if transport == 'serial':
                self._connect_serial()
            else:
                uri = self.get_parameter('device_uri').get_parameter_value().string_value
                self._connect_ws(uri)

    # ============================ Serial RX ============================

    def _serial_on_bytes(self, raw: bytes):
        if not raw:
            return
        if self._serial_debug:
            preview = ' '.join(f'{b:02X}' for b in raw[:64])
            self.get_logger().info(f'Serial RX raw: {preview}' + (' …' if len(raw) > 64 else ''))

        # Decide mode if we're still in 'auto'
        if self._serial_mode == 'auto':
            # Heuristic:
            # - If many bytes have MSB set or we see OA escapes → OverAscii
            # - If mostly printable ASCII with CR/LF → console ASCII
            high = sum(1 for b in raw if (b >= 0x80) or (b in (0x85, 0x8E, 0x8F)))
            printable = sum(1 for b in raw if (32 <= b < 127) or (b in (9, 10, 13)))
            if high > max(8, len(raw) // 4):
                self._serial_mode = 'overascii'
                self.get_logger().warn('Serial mode auto-detect: OVERASCII (RICSerial tunneled)')
            elif printable >= max(8, len(raw) // 2) and any(b in raw for b in (10, 13)):
                self._serial_mode = 'ascii'
                self.get_logger().warn('Serial mode auto-detect: ASCII CONSOLE')

        # Dispatch by decided/forced mode
        if self._serial_mode == 'overascii':
            self._oa.feed(raw)          # decoded binary → HDLC deframer → dispatcher
        else:
            self._feed_console(raw)     # ASCII: accumulate and extract JSON replies

    def _feed_console(self, raw: bytes):
        self._console_buf.extend(raw)
        if len(self._console_buf) > 65536:
            self._console_buf = self._console_buf[-32768:]

        text = self._console_buf.decode('utf-8', errors='ignore')
        start = text.rfind('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            js = text[start:end+1]
            self._console_buf = bytearray(text[end+1:].encode('utf-8', errors='ignore'))
            try:
                obj = json.loads(js)
            except Exception:
                return

            # 1) Wake any waiting RPC (e.g., version query)
            ev = self._console_wait_ev
            if ev is not None:
                self._console_resp_buf = js.encode('utf-8')
                ev.set()

            # 2) Also treat as a potential publish payload
            try:
                if isinstance(obj, dict) and obj:     # devjson style payloads are dicts
                    self._dispatch_sensor_payload(obj)
            except Exception:
                pass

    # ============================ WebSocket (data) ============================

    def _on_open_data(self, ws):
        self.get_logger().info('Data WS opened')
        self.state._opened_event.set()
        try:
            subscribe_cmd = {
                'cmdName': 'subscription',
                'action': 'update',
                'pubRecs': [
                    {'name': 'devjson', 'trigger': 'timeorchange', 'rateHz': 0.1},
                ],
            }
            ws.send(json.dumps(subscribe_cmd))
        except Exception as e:
            self.get_logger().warn(f'Failed to send subscription: {e}')

    def _on_message_data(self, ws, message):
        if isinstance(message, (bytes, bytearray)):
            return
        try:
            data = json.loads(message)
        except Exception:
            self.get_logger().debug('Data WS: non-JSON text frame ignored')
            return
        self._dispatch_sensor_payload(data)

    def _on_error_data(self, ws, error):
        self.get_logger().error(f'Data WS error: {error}')
        self.state.last_error = str(error)
        self.state._error_event.set()

    def _on_close_data(self, ws, code, reason):
        self.get_logger().info(f'Data WS closed: code={code} reason={reason}')

    # ============================ WebSocket (control) ============================

    def _on_open_ctrl(self, ws):
        self.get_logger().info('Control WS opened')

    def _on_message_ctrl(self, ws, message):
    # Binary frames carry a RICFrame or an HDLC-wrapped RICFrame
        mode = self._ws_mode()
        if isinstance(message, (bytes, bytearray)):
            buf = bytes(message)
            if mode == 'RICSerial':
                ok, payload = self._mini_hdlc.try_decode(buf)
                if not ok:
                    self.get_logger().warn('Control WS: HDLC decode failed (crc/framing)')
                    return
                ric = payload
            else:
                ric = buf

            if len(ric) < 3:
                return

            typeproto = ric[1]
            if typeproto != pack_type_proto(TYPE_RESPONSE, PROTO_RICREST):
                return

            elem = ric[2]
            if elem != ELEM_CMDRESPJSON:
                return

            # JSON text (NUL-terminated)
            body = ric[3:]
            nul = body.find(b'\x00')
            json_text = body[:nul] if nul >= 0 else body

            msgnum = ric[0]
            with self._ric_lock:
                ev = self._ric_wait.get(msgnum)
                if ev is not None:
                    self._ric_resp[msgnum] = json_text
                    ev.set()
            return

        # Text frames may be present if pcol=RICJSON
        try:
            _ = json.loads(message)
            self.get_logger().debug('Control WS text frame received (RICJSON?)')
        except Exception:
            self.get_logger().debug('Control WS: non-JSON text ignored')

    def _on_error_ctrl(self, ws, error):
        self.get_logger().error(f'Control WS error: {error}')

    def _on_close_ctrl(self, ws, code, reason):
        self.get_logger().info(f'Control WS closed: code={code} reason={reason}')

    # ============================ Connect / Disconnect ============================

    def _connect_ws(self, device_uri: str, timeout_s: float = 10.0):
        if websocket is None:
            self.state.last_error = 'Missing dependency: websocket-client'
            self.get_logger().error(self.state.last_error)
            return False, 'websocket-client not installed'

        if self.state.connected:
            return True, 'Already connected'

        self.state._opened_event.clear()
        self.state._error_event.clear()

        self.state.uri = device_uri
        control_uri = self.get_parameter('control_uri').value
        if not control_uri:
            try:
                scheme, rest = device_uri.split('://', 1)
                host = rest.split('/', 1)[0]
                ws_path = self.get_parameter('ws_path').value or '/ws'
                control_uri = f'{scheme}://{host}{ws_path}'
            except Exception:
                control_uri = ''

    # Data WebSocket
        self.state.data_ws = websocket.WebSocketApp(
            device_uri,
            on_open=self._on_open_data,
            on_message=self._on_message_data,
            on_error=self._on_error_data,
            on_close=self._on_close_data,
        )
        self.state.data_thread = threading.Thread(target=self.state.data_ws.run_forever, daemon=True)
        self.state.data_thread.start()

    # Control WebSocket (optional second channel)
        if self.get_parameter('use_dual_ws').value and control_uri:
            self.state.ctrl_ws = websocket.WebSocketApp(
                control_uri,
                on_open=self._on_open_ctrl,
                on_message=self._on_message_ctrl,
                on_error=self._on_error_ctrl,
                on_close=self._on_close_ctrl,
            )
            self.state.ctrl_thread = threading.Thread(target=self.state.ctrl_ws.run_forever, daemon=True)
            self.state.ctrl_thread.start()
        else:
            self.state.ctrl_ws = None
            self.state.ctrl_thread = None

    # Wait for data WebSocket to open
        start = time.time()
        while time.time() - start < timeout_s:
            if self.state._opened_event.is_set():
                self.state.connected = True
                self.state.last_error = ''
                return True, 'Connected'
            if self.state._error_event.is_set():
                self.state.connected = False
                return False, f'Failed to connect: {self.state.last_error}'
            time.sleep(0.05)

        self.state.connected = False
        return False, 'Timed out waiting for connection'

    def _connect_serial(self):
        if self.state.connected:
            return True, 'Already connected'
        port = self.get_parameter('serial.port').value
        baud = int(self.get_parameter('serial.baud').value)
        timeout = float(self.get_parameter('serial.timeout').value)

        st = SerialTransport(port=port, baud=baud, timeout=timeout)
        self.state.serial_transport = st

        st.on_status = self._on_serial_status
        st.on_bytes = self._serial_on_bytes

        self.get_logger().info(f'Opening serial: port={port} baud={baud} timeout={timeout}')
        st.start()
        self.state.uri = port
        return True, 'Connecting serial'

    def _disconnect(self):
        try:
            if self.state.data_ws is not None:
                self.state.data_ws.close()
        except Exception as e:
            self.get_logger().warn(f'Data WS close error: {e}')
        try:
            if self.state.ctrl_ws is not None:
                self.state.ctrl_ws.close()
        except Exception as e:
            self.get_logger().warn(f'Control WS close error: {e}')
        try:
            if self.state.serial_transport is not None:
                self.state.serial_transport.stop()
        except Exception as e:
            self.get_logger().warn(f'Serial stop error: {e}')

        self._dispatcher.reset_waiters('disconnect')
        self.state.connected = False
        return True, 'Disconnected'

    # ============================ Services ============================

    def handle_connect(self, request: Connect.Request, response: Connect.Response):
        transport = self.get_parameter('transport').get_parameter_value().string_value
        if transport == 'serial':
            ok, msg = self._connect_serial()
        else:
            uri = request.device_uri or self.state.uri or self.get_parameter('device_uri').value
            ok, msg = self._connect_ws(uri)
        response.success = ok
        response.message = msg
        return response

    def handle_disconnect(self, _request: Disconnect.Request, response: Disconnect.Response):
        ok, msg = self._disconnect()
        response.success = ok
        response.message = msg
        return response

    def handle_ping(self, request: Ping.Request, response: Ping.Response):
    # Quick RTT estimate over the data channel
        if not self.state.connected or self.state.data_ws is None:
            response.success = False
            response.rtt_ms = 0.0
            response.message = 'Not connected'
            return response
        try:
            payload = 'x' * int(request.payload_size)
            t0 = time.time()
            self.state.data_ws.send(json.dumps({'cmdName': 'ping', 'payload': payload}))
            time.sleep(0.01)
            response.success = True
            response.rtt_ms = float((time.time() - t0) * 1000.0)
            response.message = 'RTT estimated'
        except Exception as e:
            response.success = False
            response.rtt_ms = 0.0
            response.message = f'Ping failed: {e}'
        return response

    def handle_get_state(self, _request: GetConnectionState.Request, response: GetConnectionState.Response):
        response.connected = self.state.connected
        response.device_uri = self.state.uri
        response.last_error = self.state.last_error
        return response

    def handle_ric_rest_url(self, req: RicRestUrl.Request, res: RicRestUrl.Response):
        """
        Send a RICREST URL request and await CMDRESPJSON.
        - WS: sends RICFrame (or HDLC-wrapped) over control WS
        - Serial:
            * ascii     → "url\n" and parse console JSON
            * overascii → OverAscii(HDLC(RICFrame))
            * auto      → if still 'auto', prefer ascii first (works with 'v'), OverAscii will auto-switch on RX
        """
        transport_kind = self.get_parameter('transport').get_parameter_value().string_value
        timeout = req.timeout if req.timeout > 0 else float(self.get_parameter('rpc_default_timeout').value)
        url_str = (req.url_path or '').strip()

        # ---- Serial path ----
        if transport_kind == 'serial':
            st = self.state.serial_transport
            if st is None:
                res.success = False; res.message = 'Serial transport not started'; return res

            mode = self._serial_mode
            # ---- Serial ASCII console request/response ----
            if mode in ('ascii', 'auto'):
                line = (url_str).strip()


                ev = threading.Event()
                with self._ric_lock:
                    self._console_wait_ev = ev
                    self._console_resp_buf = None

                try:
                    st.send((line + '\n').encode('utf-8'))
                except Exception as e:
                    with self._ric_lock:
                        self._console_wait_ev = None
                        self._console_resp_buf = None
                    res.success = False
                    res.message = f'serial send failed: {e}'
                    return res

                if not ev.wait(timeout):
                    with self._ric_lock:
                        self._console_wait_ev = None
                        self._console_resp_buf = None
                    res.success = False
                    res.message = 'timeout'
                    return res

                with self._ric_lock:
                    data = self._console_resp_buf or b''
                    self._console_wait_ev = None
                    self._console_resp_buf = None

                res.success = True
                res.json_text = data.decode('utf-8', errors='replace')
                res.message = 'OK'
                return res

            # OverAscii + RICSerial
            msgnum = self._dispatcher.next_msgnum()
            proto_name = str(self.get_parameter('ricrest_proto').value or 'RICREST').upper()
            proto_id = PROTO_BRIDGE_RICREST if proto_name == 'BRIDGE_RICREST' else PROTO_RICREST
            ric = RICFrame.pack(msgnum, pack_type_proto(TYPE_COMMAND, proto_id), ELEM_URL, url_str.encode('utf-8'))
            hdlc = self._ric_serial.encode(ric)

            payload = overascii_encode(hdlc)

            ev = self._dispatcher.register_waiter(msgnum)
            self.get_logger().info(f'Sending RICREST(URL) over serial(OverAscii): msgnum={msgnum} path={url_str}')
            self.get_logger().debug('TX(serial,overascii+hdlc)[:40]= ' + payload[:40].hex() + ('...' if len(payload) > 40 else ''))
            try:
                st.send(payload)
            except Exception as e:
                res.success = False; res.message = f'serial send failed: {e}'; return res

            if not ev.wait(timeout):
                self._dispatcher.pop_payload(msgnum)
                res.success = False; res.message = 'timeout'; return res

            data = self._dispatcher.pop_payload(msgnum)
            res.success = True; res.json_text = data.decode('utf-8', errors='replace'); res.message = 'OK'; return res

        # ---- WebSocket path ----
        if not self.state.connected:
            res.success = False; res.message = 'Not connected'; return res

        ws = self.state.ctrl_ws if self.state.ctrl_ws is not None else self.state.data_ws
        if ws is None:
            res.success = False; res.message = 'No WebSocket available'; return res

        msgnum = self._next_msgnum()
        proto_name = str(self.get_parameter('ricrest_proto').value or 'RICREST').upper()
        proto_id = PROTO_BRIDGE_RICREST if proto_name == 'BRIDGE_RICREST' else PROTO_RICREST
        ric = RICFrame.pack(msgnum, pack_type_proto(TYPE_COMMAND, proto_id), ELEM_URL, url_str.encode('utf-8'))
        mode = self._ws_mode(req.ws_pcol)
        payload = self._mini_hdlc.encode(ric) if mode == 'RICSerial' else ric

        ev = threading.Event()
        with self._ric_lock:
            self._ric_wait[msgnum] = ev
            self._ric_resp.pop(msgnum, None)

        try:
            ws.send(payload, opcode=0x2)  # binary
        except Exception as e:
            with self._ric_lock:
                self._ric_wait.pop(msgnum, None)
            res.success = False; res.message = f'send failed: {e}'; return res

        if not ev.wait(timeout):
            with self._ric_lock:
                self._ric_wait.pop(msgnum, None)
            res.success = False; res.message = 'timeout'; return res

        with self._ric_lock:
            data = self._ric_resp.pop(msgnum, b'')
            self._ric_wait.pop(msgnum, None)

        res.success = True
        res.json_text = data.decode('utf-8', errors='replace')
        res.message = 'OK'
        return res

    # ============================ Helpers ============================

    def _dispatch_sensor_payload(self, data: Dict):
        frame_id = self.get_parameter('frame_id').get_parameter_value().string_value
        for bus, devs in data.items():
            for addr, pkt in devs.items():
                tkey = pkt.get('_t', '')
                hex_data = pkt.get('x', '')
                dec = get_decoder(tkey, frame_id)
                if not dec or not hex_data:
                    continue
                for topic_suffix, ros_msg in dec.decode_samples(hex_data):
                    topic = f"{tkey}_{addr}/{topic_suffix}"
                    pub = self.publisher_cache.get(topic, type(ros_msg))
                    pub.publish(ros_msg)

    def _next_msgnum(self) -> int:
        with self._ric_lock:
            n = self._ric_msgnum
            self._ric_msgnum = 1 if n >= 255 else n + 1
            return n

    def _ws_mode(self, override: Optional[str] = None) -> str:
        return (override or self.get_parameter('ws_pcol').value or 'RICSerial').strip()

    # ============================ Serial callbacks ============================

    def _on_serial_status(self, connected: bool, msg: str):
        if connected:
            self.get_logger().info('Serial status: connected')
            self.state.connected = True
            self.state.last_error = ''
        else:
            self.state.connected = False
            if msg:
                self.state.last_error = msg
            self.get_logger().warn(f'Serial status: disconnected ({msg})')
            self._dispatcher.reset_waiters('serial status change')

    def _handle_publish_frame(self, frame: bytes):
        if len(frame) < 3:
            return
        msgnum, tprot = frame[0], frame[1]
        msg_type = (tprot >> 6) & 0x3
        proto    =  tprot       & 0x3F

        # RAWCMDFRAME (RICJSON) publish 	 payload is JSON (may be NUL-terminated)
        if msg_type == TYPE_PUBLISH and proto == PROTO_RAWCMDFRAME:
            body = frame[2:]
            nul = body.find(b'\x00')
            if nul >= 0:
                body = body[:nul]
            try:
                obj = json.loads(body.decode('utf-8', errors='replace'))
                if isinstance(obj, dict):
                    self._dispatch_sensor_payload(obj)
                else:
                    self.get_logger().debug('Publish RAWCMDFRAME is not a dict; ignoring')
            except Exception as e:
                self.get_logger().debug(f'Publish RAWCMDFRAME JSON decode failed: {e}')
            return

        # Fallback: some builds publish via RICREST/CMDRESPJSON
        if msg_type == TYPE_PUBLISH and proto == PROTO_RICREST and len(frame) >= 4:
            elem = frame[2]
            if elem == ELEM_CMDRESPJSON:
                body = frame[3:]
                nul = body.find(b'\x00')
                if nul >= 0:
                    body = body[:nul]
                try:
                    obj = json.loads(body.decode('utf-8', errors='replace'))
                    if isinstance(obj, dict):
                        self._dispatch_sensor_payload(obj)
                except Exception as e:
                    self.get_logger().debug(f'Publish RICREST JSON decode failed: {e}')
            return

        # Otherwise, log for visibility
        self.get_logger().debug(f'Unhandled publish/report frame: type={msg_type} proto={proto} len={len(frame)}')

    def _on_serial_frame(self, frame: bytes):
        if len(frame) >= 3:
            msgnum, tprot, elem0 = frame[0], frame[1], frame[2]
            mtype = (tprot >> 6) & 0x3
            proto = (tprot & 0x3F)

            # Debug header
            self.get_logger().debug(
                f'Serial frame: msgnum={msgnum} type={mtype} proto={proto} elem={elem0 if len(frame)>2 else -1} len={len(frame)}'
            )

            # ---- Handle PUBLISH frames with JSON payload ----
            if mtype == TYPE_PUBLISH:
                try:
                    if proto == PROTO_RAWCMDFRAME:
                        # Body is raw JSON (possibly NUL-terminated)
                        body = frame[2:]
                        nul = body.find(b'\x00')
                        body = body[:nul] if nul >= 0 else body
                        text = body.decode('utf-8', errors='replace')
                        data = json.loads(text)
                        self._dispatch_sensor_payload(data)
                        return
                    elif proto == PROTO_RICREST and elem0 == ELEM_CMDRESPJSON:
                        # Some builds use RICREST/CMDRESPJSON for publishes
                        body = frame[3:]
                        nul = body.find(b'\x00')
                        body = body[:nul] if nul >= 0 else body
                        text = body.decode('utf-8', errors='replace')
                        data = json.loads(text)
                        self._dispatch_sensor_payload(data)
                        return
                except Exception as e:
                    self.get_logger().warn(f'Publish parse failed: {e}')
                    return

    # Not a publish → hand to dispatcher (matches responses for RPC)
        self._dispatcher.handle_frame(frame)


# ---------------------------- Entrypoint ----------------------------

def main(args=None):
    try:
        rclpy.init(args=args)
        node = AxiomBridgeNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        rclpy.shutdown()