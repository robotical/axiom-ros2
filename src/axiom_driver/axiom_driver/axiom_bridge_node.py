import time
import threading
import json
from typing import Dict, Optional

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException

from axiom_driver.ric_consts import (
    TYPE_COMMAND, TYPE_RESPONSE,
    PROTO_RICREST,
    ELEM_URL, ELEM_CMDRESPJSON,
    pack_type_proto,
)
from axiom_driver.mini_hdlc import MiniHDLC, FLAG_DEFAULT, ESC_DEFAULT, XOR_DEFAULT
from axiom_driver.sensors.registry import get_decoder
from axiom_driver.publisher_cache import PublisherCache

from axiom_interfaces.srv import (
    Connect, Disconnect, Ping, GetConnectionState, RicRestUrl
)

# External dependency: websocket-client
try:
    import websocket  # type: ignore
except ImportError:  # pragma: no cover
    websocket = None


class ConnectionState:
    """Holds connection state for both data and control sockets."""
    def __init__(self):
        self.connected: bool = False
        self.uri: str = ''
        self.last_error: str = ''

        # Data channel (sensor JSON, e.g., /devjson)
        self.data_ws: Optional[websocket.WebSocketApp] = None
        self.data_thread: Optional[threading.Thread] = None

        # Control channel (RIC/REST, e.g., /ws)
        self.ctrl_ws: Optional[websocket.WebSocketApp] = None
        self.ctrl_thread: Optional[threading.Thread] = None

        # Handshake events (for connect())
        self._opened_event = threading.Event()
        self._error_event = threading.Event()


class AxiomBridgeNode(Node):
    def __init__(self):
        super().__init__('axiom_bridge_node')

        # ===== Parameters =====
        # Core
        self.declare_parameter('device_uri', 'ws://')        # e.g., ws://192.168.1.7/devjson
        self.declare_parameter('auto_connect', False)
        self.declare_parameter('frame_id', 'axiom_link')

        # Dual-WS control channel
        self.declare_parameter('use_dual_ws', True)          # open /ws alongside /devjson
        self.declare_parameter('ws_path', '/ws')             # control WS path if control_uri empty
        self.declare_parameter('control_uri', '')            # override full control ws URI if set
        self.declare_parameter('ws_pcol', 'RICSerial')       # RICSerial | RICFrame | RICJSON

        # RPC / HDLC
        self.declare_parameter('rpc_default_timeout', 3.0)
        self.declare_parameter('hdlc_flag', FLAG_DEFAULT)
        self.declare_parameter('hdlc_escape', ESC_DEFAULT)
        self.declare_parameter('hdlc_xor', XOR_DEFAULT)

        # ===== Members =====
        self.state = ConnectionState()
        self.publisher_cache = PublisherCache(self)

        # RIC/REST tracking
        self._ric_msgnum = 1
        self._ric_lock = threading.Lock()
        self._ric_wait: Dict[int, threading.Event] = {}
        self._ric_resp: Dict[int, bytes] = {}
        self._mini_hdlc = MiniHDLC(
            self.get_parameter('hdlc_flag').value,
            self.get_parameter('hdlc_escape').value,
            self.get_parameter('hdlc_xor').value,
        )

        # ===== Services =====
        self.create_service(Connect, 'connect', self.handle_connect)
        self.create_service(Disconnect, 'disconnect', self.handle_disconnect)
        self.create_service(Ping, 'ping', self.handle_ping)
        self.create_service(GetConnectionState, 'get_connection_state', self.handle_get_state)
        self.create_service(RicRestUrl, 'ric_rest_url', self.handle_ric_rest_url)

        # ===== Autoconnect =====
        if self.get_parameter('auto_connect').get_parameter_value().bool_value:
            uri = self.get_parameter('device_uri').get_parameter_value().string_value
            self._connect(uri)

    # =========================================================
    # WebSocket: data (JSON stream)
    # =========================================================
    def _on_open_data(self, ws):
        self.get_logger().info('Data WS opened')
        # Mark "opened" for connect handshake when data channel comes up
        self.state._opened_event.set()
        # Subscribe to devjson stream
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
        # Expect JSON payloads for sensor data
        if isinstance(message, (bytes, bytearray)):
            # Some firmwares may push binary on data WS—ignore here
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

    # =========================================================
    # WebSocket: control (RIC/REST)
    # =========================================================
    def _on_open_ctrl(self, ws):
        self.get_logger().info('Control WS opened')

    def _on_message_ctrl(self, ws, message):
        """Parse RIC/REST replies arriving on control WS."""
        # Text frames could be RICJSON; binary frames carry RICFrame or HDLC(RICFrame)
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
                ric = buf  # raw RICFrame

            if len(ric) < 3:
                return

            msgnum = ric[0]
            typeproto = ric[1]
            if typeproto != pack_type_proto(TYPE_RESPONSE, PROTO_RICREST):
                # Not a RICREST RESPONSE; ignore (could add other protocol handlers later)
                return

            elem = ric[2]
            if elem != ELEM_CMDRESPJSON:
                # For URL flow we expect CMDRESPJSON back
                return

            # JSON text (NUL-terminated)
            json_bytes = ric[3:]
            nul = json_bytes.find(b'\x00')
            json_text = json_bytes[:nul].decode('utf-8', errors='replace') if nul >= 0 else json_bytes.decode('utf-8', errors='replace')

            with self._ric_lock:
                ev = self._ric_wait.get(msgnum)
                if ev is not None:
                    self._ric_resp[msgnum] = json_text.encode('utf-8')
                    ev.set()
            return

        # Optional: handle RICJSON here if your control channel uses pcol="RICJSON"
        try:
            data = json.loads(message)
            # If we add RICJSON request/response later, match by some correlation key here.
            self.get_logger().debug(f'Control WS text: {data}')
        except Exception:
            self.get_logger().debug('Control WS: non-JSON text ignored')

    def _on_error_ctrl(self, ws, error):
        self.get_logger().error(f'Control WS error: {error}')

    def _on_close_ctrl(self, ws, code, reason):
        self.get_logger().info(f'Control WS closed: code={code} reason={reason}')

    # =========================================================
    # Connect / Disconnect (dual WS)
    # =========================================================
    def _connect(self, device_uri: str, timeout_s: float = 10.0):
        if websocket is None:
            self.state.last_error = 'Missing dependency: websocket-client'
            self.get_logger().error(self.state.last_error)
            return False, 'websocket-client not installed'

        if self.state.connected:
            return True, 'Already connected'

        self.state._opened_event.clear()
        self.state._error_event.clear()

        # Build URIs
        self.state.uri = device_uri
        control_uri = self.get_parameter('control_uri').value
        if not control_uri:
            # Derive ws://host[:port]/<ws_path> from device_uri
            try:
                # basic split without importing urlparse (keeps deps small)
                scheme, rest = device_uri.split('://', 1)
                host_and_path = rest.split('/', 1)
                host = host_and_path[0]
                ws_path = self.get_parameter('ws_path').value or '/ws'
                control_uri = f'{scheme}://{host}{ws_path}'
            except Exception:
                control_uri = ''  # fallback

        # Data WS (sensor stream)
        self.state.data_ws = websocket.WebSocketApp(
            device_uri,
            on_open=self._on_open_data,
            on_message=self._on_message_data,
            on_error=self._on_error_data,
            on_close=self._on_close_data,
        )
        self.state.data_thread = threading.Thread(target=self.state.data_ws.run_forever, daemon=True)
        self.state.data_thread.start()

        # Control WS (RIC/REST)
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

        # Wait for either open or error (data WS dictates readiness)
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

    def _disconnect(self):
        # Close both sockets if open
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

        self.state.connected = False
        return True, 'Disconnected'

    # =========================================================
    # Services
    # =========================================================
    def handle_connect(self, request: Connect.Request, response: Connect.Response):
        uri = request.device_uri or self.state.uri or self.get_parameter('device_uri').value
        ok, msg = self._connect(uri)
        response.success = ok
        response.message = msg
        return response

    def handle_disconnect(self, _request: Disconnect.Request, response: Disconnect.Response):
        ok, msg = self._disconnect()
        response.success = ok
        response.message = msg
        return response

    def handle_ping(self, request: Ping.Request, response: Ping.Response):
        # Minimal stub over data WS; replace with a real echo if firmware has one
        if not self.state.connected or self.state.data_ws is None:
            response.success = False
            response.rtt_ms = 0.0
            response.message = 'Not connected'
            return response
        try:
            payload = 'x' * int(request.payload_size)
            t0 = time.time()
            echo_cmd = {'cmdName': 'ping', 'payload': payload}
            self.state.data_ws.send(json.dumps(echo_cmd))
            time.sleep(0.01)
            response.success = True
            response.rtt_ms = float((time.time() - t0) * 1000.0)
            response.message = 'RTT estimated (stub)'
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
        """Send a RICREST URL request over the control WS and await CMDRESPJSON."""
        if not self.state.connected:
            res.success = False
            res.message = 'Not connected'
            return res

        # Choose WS for control
        ws = self.state.ctrl_ws if self.state.ctrl_ws is not None else self.state.data_ws
        if ws is None:
            res.success = False
            res.message = 'No WebSocket available'
            return res

        url = (req.url_path or '').encode('utf-8')
        msgnum = self._next_msgnum()
        hdr = bytes([msgnum, pack_type_proto(TYPE_COMMAND, PROTO_RICREST), ELEM_URL])
        ric = hdr + url

        mode = self._ws_mode(req.ws_pcol)
        payload = self._mini_hdlc.encode(ric) if mode == 'RICSerial' else ric

        # Register waiter
        ev = threading.Event()
        with self._ric_lock:
            self._ric_wait[msgnum] = ev
            self._ric_resp.pop(msgnum, None)

        # Send as binary
        try:
            ws.send(payload, opcode=0x2)
        except Exception as e:
            with self._ric_lock:
                self._ric_wait.pop(msgnum, None)
            res.success = False
            res.message = f'send failed: {e}'
            return res

        timeout = req.timeout if req.timeout > 0 else self.get_parameter('rpc_default_timeout').value
        if not ev.wait(timeout):
            with self._ric_lock:
                self._ric_wait.pop(msgnum, None)
            res.success = False
            res.message = 'timeout'
            return res

        with self._ric_lock:
            data = self._ric_resp.pop(msgnum, b'')
            self._ric_wait.pop(msgnum, None)

        res.success = True
        res.json_text = data.decode('utf-8', errors='replace')
        res.message = 'OK'
        return res

    # =========================================================
    # Helpers
    # =========================================================
    def _dispatch_sensor_payload(self, data: Dict):
        """Decode sensor JSON and publish ROS messages via decoder plugins."""
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


def main(args=None):
    try:
        rclpy.init(args=args)
        node = AxiomBridgeNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        rclpy.shutdown()