"""ROS2 node providing a bridge between Axiom device transports and ROS topics.

This file used to be a large monolithic implementation. It has been split
into smaller modules located in:
  - bridge_connection.py (ConnectionState)
  - bridge_mixins.py (Serial / WebSocket / Publish / Sensor payload logic)

Behaviour is intentionally unchanged.
"""

import time
import threading
import json
from typing import Optional, Tuple

import rclpy
from rclpy.node import Node
from rclpy.executors import ExternalShutdownException
from std_msgs.msg import String

from .bridge_connection import ConnectionState
from .bridge_mixins.ws_mixin import WebSocketMixin
from .bridge_mixins.serial_mixin import SerialMixin 
from .bridge_mixins.publish_mixin import PublishMixin 
from .bridge_mixins.sensor_payload_mixin import SensorPayloadMixin
from .ric_consts import (
    TYPE_COMMAND,
    PROTO_RICREST, PROTO_BRIDGE_RICREST,
    ELEM_URL,
    pack_type_proto,
)
from .mini_hdlc import MiniHDLC, FLAG_DEFAULT, ESC_DEFAULT, XOR_DEFAULT
from .publisher_cache import PublisherCache
from .protocols.dispatcher import Dispatcher
from .protocols.ric_frame import RICFrame
from .protocols.ric_serial import RICSerial
from .protocols.overascii import Decoder as OverAsciiDecoder, encode as overascii_encode
from .ric_consts import TYPE_PUBLISH, PROTO_RAWCMDFRAME, PROTO_ROSSERIAL
from axiom_interfaces.srv import (
    Connect, Disconnect, Ping, GetConnectionState, RicRestUrl, PublishedDataSubscription
)


class AxiomBridgeNode(Node, WebSocketMixin, SerialMixin, PublishMixin, SensorPayloadMixin):
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
        self.declare_parameter('autosub', False)
        self.declare_parameter('serial.devjson_rate_hz', 0.1)
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
        self._ric_wait = {}
        self._ric_resp = {}

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
        self._console_wait_ev = None  # type: Optional[threading.Event]
        self._console_resp_buf = None  # type: Optional[bytes]
        self._serial_debug = bool(self.get_parameter('debug_hex').value)

        # Publishers
        self._console_pub = self.create_publisher(
            msg_type=String,
            topic='serial_console',
            qos_profile=10
        )

        # Device type information cache (for dynamic decoder discovery)
        self._device_typeinfo_cache = {}
        self._device_typeinfo_lock = threading.Lock()
        self._device_typeinfo_retry_window = 5.0
        self._device_typeinfo_request_timeout = 2.0

        # Subscription tracking

        # WS helpers
        self.ws_data_opened = False

        # ===== Services =====
        self.create_service(Connect, 'connect', self.handle_connect)
        self.create_service(Disconnect, 'disconnect', self.handle_disconnect)
        self.create_service(Ping, 'ping', self.handle_ping)
        self.create_service(GetConnectionState, 'get_connection_state', self.handle_get_state)
        self.create_service(RicRestUrl, 'ric_rest_url', self.handle_ric_rest_url)
        self.create_service(PublishedDataSubscription, 'publish_data_subscription', self.handle_published_data_subscription)

        # ===== Autoconnect =====
        if self.get_parameter('auto_connect').get_parameter_value().bool_value:
            transport = self.get_parameter('transport').get_parameter_value().string_value
            if transport == 'serial':
                self._connect_serial()
            else:
                uri = self.get_parameter('device_uri').get_parameter_value().string_value
                self._connect_ws(uri)
    # ============================ Connect / Disconnect ============================

    def _disconnect(self):
        try:
            if self.state.data_ws is not None:
                self.state.data_ws.close()
        except Exception as e:
            self.get_logger().warn(f'Data WS close error: {e}')
        finally:
            thread = getattr(self.state, 'data_thread', None)
            if thread is not None and thread.is_alive():
                thread.join(timeout=1.0)
            self.state.data_thread = None
            self.state.data_ws = None
        try:
            if self.state.ctrl_ws is not None:
                self.state.ctrl_ws.close()
        except Exception as e:
            self.get_logger().warn(f'Control WS close error: {e}')
        finally:
            thread = getattr(self.state, 'ctrl_thread', None)
            if thread is not None and thread.is_alive():
                thread.join(timeout=1.0)
            self.state.ctrl_thread = None
            self.state.ctrl_ws = None
        try:
            if self.state.serial_transport is not None:
                self.state.serial_transport.stop()
        except Exception as e:
            self.get_logger().warn(f'Serial stop error: {e}')
        finally:
            self.state.serial_transport = None

        self._dispatcher.reset_waiters('disconnect')
        self.state.connected = False
        self.ws_data_opened = False
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
        timeout = req.timeout if req.timeout > 0 else None
        success, message, payload = self._send_ric_rest_url(
            (req.url_path or '').strip(),
            timeout=timeout,
            ws_pcol_override=req.ws_pcol
        )

        res.success = success
        res.message = message
        res.json_text = (payload or b'').decode('utf-8', errors='replace') if payload else ''
        return res

    def _send_ric_rest_url(
        self,
        url_path: str,
        *,
        timeout: Optional[float] = None,
        ws_pcol_override: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[bytes]]:
        transport_kind = self.get_parameter('transport').get_parameter_value().string_value
        timeout_s = timeout if timeout and timeout > 0 else float(self.get_parameter('rpc_default_timeout').value)
        url_str = (url_path or '').strip()

        # ---- Serial path ----
        if transport_kind == 'serial':
            st = self.state.serial_transport
            if st is None:
                return False, 'Serial transport not started', None

            mode = self._serial_mode
            # ---- Serial ASCII console request/response ----
            if mode in ('ascii', 'auto'):
                line = url_str

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
                    return False, f'serial send failed: {e}', None

                if not ev.wait(timeout_s):
                    with self._ric_lock:
                        self._console_wait_ev = None
                        self._console_resp_buf = None
                    return False, 'timeout', None

                with self._ric_lock:
                    data = self._console_resp_buf or b''
                    self._console_wait_ev = None
                    self._console_resp_buf = None

                return True, 'OK', data

            # OverAscii + RICSerial
            msgnum = self._dispatcher.next_msgnum()
            proto_name = str(self.get_parameter('ricrest_proto').value or 'RICREST').upper()
            proto_id = PROTO_BRIDGE_RICREST if proto_name == 'BRIDGE_RICREST' else PROTO_RICREST
            ric = RICFrame.pack(msgnum, pack_type_proto(TYPE_COMMAND, proto_id), ELEM_URL, url_str.encode('utf-8'))
            hdlc = self._ric_serial.encode(ric)

            payload = overascii_encode(hdlc)

            ev = self._dispatcher.register_waiter(msgnum)
            self.get_logger().info(f'Sending RICREST(URL) over serial(OverAscii): msgnum={msgnum} path={url_str}')
            self.get_logger().info('TX(serial,overascii+hdlc)[:40]= ' + payload[:40].hex() + ('...' if len(payload) > 40 else ''))
            try:
                st.send(payload)
            except Exception as e:
                return False, f'serial send failed: {e}', None

            if not ev.wait(timeout_s):
                self._dispatcher.pop_payload(msgnum)
                return False, 'timeout', None

            data = self._dispatcher.pop_payload(msgnum)
            return True, 'OK', data

        # ---- WebSocket path ----
        if not self.state.connected:
            return False, 'Not connected', None

        ws = self.state.ctrl_ws if self.state.ctrl_ws is not None else self.state.data_ws
        if ws is None:
            return False, 'No WebSocket available', None

        msgnum = self._next_msgnum()
        proto_name = str(self.get_parameter('ricrest_proto').value or 'RICREST').upper()
        proto_id = PROTO_BRIDGE_RICREST if proto_name == 'BRIDGE_RICREST' else PROTO_RICREST
        ric = RICFrame.pack(msgnum, pack_type_proto(TYPE_COMMAND, proto_id), ELEM_URL, url_str.encode('utf-8'))
        mode = self._ws_mode(ws_pcol_override)
        payload = self._mini_hdlc.encode(ric) if mode == 'RICSerial' else ric

        # dump the inner RIC frame and the on-wire payload
        self.get_logger().info(
            f'WS TX: msgnum={msgnum} mode={mode} proto_id={proto_id} '
            f'RIC(len={len(ric)}):{ric[:16].hex()}{"…" if len(ric)>16 else ""} '
            f'ONWIRE(len={len(payload)}):{payload[:16].hex()}{"…" if len(payload)>16 else ""}'
        )

        ev = threading.Event()
        t_send = time.time()
        with self._ric_lock:
            self._ric_wait[msgnum] = ev
            self._ric_resp.pop(msgnum, None)

        try:
            ws.send(payload, opcode=0x2)  # binary
            self.get_logger().info(f'WS TX sent: msgnum={msgnum} bytes={len(payload)}')
        except Exception as e:
            with self._ric_lock:
                self._ric_wait.pop(msgnum, None)
            self.get_logger().error(f'WS TX ERROR: msgnum={msgnum} err={e}')
            return False, f'send failed: {e}', None

        if not ev.wait(timeout_s):
            dt = time.time() - t_send
            with self._ric_lock:
                still_waiting = list(self._ric_wait.keys())
                self._ric_wait.pop(msgnum, None)
            self.get_logger().error(
                f'WS RPC TIMEOUT: msgnum={msgnum} waited={dt:.3f}s '
                f'outstanding={still_waiting}'
            )
            return False, 'timeout', None

        with self._ric_lock:
            data = self._ric_resp.pop(msgnum, b'')
            self._ric_wait.pop(msgnum, None)

        return True, 'OK', data

    def handle_published_data_subscription(self, req: PublishedDataSubscription.Request, res: PublishedDataSubscription.Response):
        """
        Subscribe the device to 'devjson' published data via the selected transport.
        """
        # ---------- Small helpers ----------
        def set_res(success: bool, msg: str):
            res.success = success
            res.message = msg
            return res

        def transport_mode() -> str:
            return self.get_parameter('transport').get_parameter_value().string_value

        def subscribe_serial(rate_hz: float):
            st = self.state.serial_transport
            if st is None:
                self.get_logger().warn('Serial transport not started')
                return set_res(False, 'Serial transport not started')
            try:
                # always send sub req OverAscii + RICSerial
                line = f'subscription?action=update&name=devjson&rateHz={rate_hz}\n'
                msgnum = self._dispatcher.next_msgnum()
                proto_name = str(self.get_parameter('ricrest_proto').value or 'RICREST').upper()
                proto_id = PROTO_BRIDGE_RICREST if proto_name == 'BRIDGE_RICREST' else PROTO_RICREST
                ric = RICFrame.pack(msgnum, pack_type_proto(TYPE_COMMAND, proto_id), ELEM_URL, line.encode('utf-8'))
                hdlc = self._ric_serial.encode(ric)

                payload = overascii_encode(hdlc)

                self.get_logger().info(f'Sending RICREST(URL) over serial(OverAscii): msgnum={msgnum} path={line}')
                self.get_logger().info('TX(serial,overascii+hdlc)[:40]= ' + payload[:40].hex() + ('...' if len(payload) > 40 else ''))
                st.send(payload)


                self.get_logger().info(f'Sent serial subscription for devjson (rate {rate_hz} Hz)')
                return set_res(True, 'Subscription sent')
            except Exception as e:
                self.get_logger().warn(f'Failed to send serial auto-subscription: {e}')
                return set_res(False, f'Failed to send subscription: {e}')

        def subscribe_ws(rate_hz: float):
            ws = self.state.data_ws
            if ws is None or not self.ws_data_opened:
                self.get_logger().warn('Data WS not open')
                return set_res(False, 'Data WS not open')
            try:
                cmd = {
                    'cmdName': 'subscription',
                    'action': 'update',
                    'pubRecs': [
                        {'name': 'devjson', 'trigger': 'timeorchange', 'rateHz': rate_hz},
                    ],
                }
                ws.send(json.dumps(cmd))
                self.get_logger().info(f'Sent subscription: {cmd}')
                return set_res(True, 'Subscription sent')
            except Exception as e:
                msg = f'Failed to send subscription: {e}'
                self.get_logger().warn(msg)
                return set_res(False, msg)

        # ---------- Pre-checks ----------
        if not self.state.connected:
            return set_res(False, 'Not connected')

        # ---------- Dispatch ----------
        mode = transport_mode()
        rate = float(req.rate_hz)

        if mode == 'serial':
            return subscribe_serial(rate)
        if mode == 'ws':
            return subscribe_ws(rate)

        return set_res(False, f'Unsupported transport: {mode}')
    # ============================ Helpers ============================

    def _next_msgnum(self) -> int:
        with self._ric_lock:
            n = self._ric_msgnum
            self._ric_msgnum = 1 if n >= 255 else n + 1
            return n

    def _ws_mode(self, override: Optional[str] = None) -> str:
        return (override or self.get_parameter('ws_pcol').value or 'RICSerial').strip()

    # ============================ Serial callbacks ============================

    # Serial + publish handlers are supplied by mixins


# ---------------------------- Entrypoint ----------------------------

def main(args=None):
    node: Optional[AxiomBridgeNode] = None
    rclpy_initialized = False
    try:
        rclpy.init(args=args)
        rclpy_initialized = True
        node = AxiomBridgeNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        if node is not None:
            node.get_logger().info('Shutting down')
    finally:
        if node is not None:
            try:
                node._disconnect()
            except Exception as exc:  # noqa: BLE001
                node.get_logger().warn(f'Disconnect during shutdown failed: {exc}')
            node.destroy_node()
        if rclpy_initialized:
            rclpy.shutdown()
