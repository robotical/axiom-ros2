
from __future__ import annotations

import json
import threading
import time
from ..bridge_mixins.sensor_payload_mixin import SensorPayloadMixin

from ..ric_consts import (
    PROTO_BRIDGE_RICREST,
    TYPE_RESPONSE,
    PROTO_RICREST,
    ELEM_CMDRESPJSON,
    pack_type_proto,
)



class WebSocketMixin(SensorPayloadMixin):
    """WebSocket connect & callbacks (data + control channels)."""

    def _connect_ws(self, device_uri: str, timeout_s: float = 10.0):
        try:
            import websocket  # type: ignore
        except ImportError:
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

        # Data WS
        self.state.data_ws = websocket.WebSocketApp(
            device_uri,
            on_open=self._on_open_data,
            on_message=self._on_message_data,
            on_error=self._on_error_data,
            on_close=self._on_close_data,
        )
        self.state.data_thread = threading.Thread(target=self.state.data_ws.run_forever, daemon=True)
        self.state.data_thread.start()

        # Control WS (optional)
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

        # Wait for data WS open
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

    # ------------- Data channel callbacks -------------
    def _on_open_data(self, ws):
        self.get_logger().info('Data WS opened, you can now send subscription requests')
        self.ws_data_opened = True
        self.state._opened_event.set()
        if (self.get_parameter('autosub').value):
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
        self.get_logger().debug(f'Data WS RX: {len(message)} bytes')
        if isinstance(message, (bytes, bytearray)):
            return
        try:
            data = json.loads(message)
        except Exception:
            self.get_logger().warn('Data WS: non-JSON text frame ignored')
            return
        self._dispatch_sensor_payload(data)

    def _on_error_data(self, ws, error):
        self.get_logger().error(f'Data WS error: {error}')
        self.state.last_error = str(error)
        self.state._error_event.set()

    def _on_close_data(self, ws, code, reason):
        self.get_logger().info(f'Data WS closed: code={code} reason={reason}')

    # ------------- Control channel callbacks -------------
    def _on_open_ctrl(self, ws):
        self.get_logger().info('Control WS opened')

    def _on_message_ctrl(self, ws, message):
        mode = self._ws_mode()
        if isinstance(message, (bytes, bytearray)):
            buf = bytes(message)
            self.get_logger().info(
                f'WS RX(bin): len={len(buf)} first={buf[:16].hex()}{"…" if len(buf)>16 else ""} mode={mode}'
            )   
            if mode == 'RICSerial':
                ok, payload = self._mini_hdlc.try_decode(buf)
                if not ok:
                    self.get_logger().warn('Control WS: HDLC decode failed (crc/framing)')
                    return
                ric = payload
                self.get_logger().info(
                    f'WS RX: HDLC ok → RIC len={len(ric)} first={ric[:16].hex()}{"…" if len(ric)>16 else ""}'
                )
            else:
                ric = buf
                self.get_logger().info(
                    f'WS RX: HDLC not used/failed(ok={ok}) → treating as RAW RIC len={len(ric)}'
                )
            if len(ric) < 3:
                self.get_logger().info('WS RX: too short for RIC header; ignoring')
                return
            typeproto = ric[1]
            if typeproto != pack_type_proto(TYPE_RESPONSE, PROTO_RICREST):
                return
            elem = ric[2]
            if elem != ELEM_CMDRESPJSON:
                return
            body = ric[3:]
            nul = body.find(b'\x00')
            json_text = body[:nul] if nul >= 0 else body
            msgnum = ric[0]
            mtype = (typeproto >> 6) & 0x3
            proto = typeproto & 0x3F
            self.get_logger().info(f'WS RX RIC: msgnum={msgnum} mtype={mtype} proto={proto} elem={elem} len={len(ric)}')

            if mtype != TYPE_RESPONSE:
                self.get_logger().info('WS RX: not a RESPONSE; ignoring')
                
            if proto not in (PROTO_RICREST, PROTO_BRIDGE_RICREST):
                self.get_logger().info(f'WS RX: unexpected proto={proto}; ignoring')
                
            if elem != ELEM_CMDRESPJSON:
                self.get_logger().info(f'WS RX: elem={elem} not CMDRESPJSON; ignoring')
                

            with self._ric_lock:
                ev = self._ric_wait.get(msgnum)
                if ev is not None:
                    self._ric_resp[msgnum] = json_text
                    ev.set()
            return
        # Text frames (RICJSON mode)
        try:
            _ = json.loads(message)
            self.get_logger().info('Control WS text frame received (RICJSON?)')
        except Exception:
            self.get_logger().info('Control WS: non-JSON text ignored')

    def _on_error_ctrl(self, ws, error):
        self.get_logger().error(f'Control WS error: {error}')

    def _on_close_ctrl(self, ws, code, reason):
        self.get_logger().info(f'Control WS closed: code={code} reason={reason}')
