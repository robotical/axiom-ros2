"""Mixins extracted from the monolithic axiom_bridge_node module.

Each mixin groups logically related behaviour (WebSocket, Serial, Publish &
Sensor dispatch) so the main node file is shorter and easier to navigate.

The mixins assume the concrete class provides:
  - get_logger()
  - parameters via get_parameter()
  - attributes initialised in the main node (__init__):
        state, _dispatcher, _mini_hdlc, _ric_serial,
        _serial_mode, _oa, _console_buf, _console_wait_ev,
        _console_resp_buf, _serial_debug, _serial_autosub_sent, 
        _console_pub,
  - helper methods: _ws_mode(), _dispatch_sensor_payload() (when needed)
  - locking attributes: _ric_lock, _ric_wait, _ric_resp (for WS control RPC)
"""

from __future__ import annotations

import json
import threading
import time
from typing import Dict, Optional
from .utils.string import find_json_fragments

from .ric_consts import (
    PROTO_BRIDGE_RICREST,
    TYPE_RESPONSE,
    PROTO_RICREST,
    ELEM_CMDRESPJSON,
    pack_type_proto,
    TYPE_PUBLISH,
    PROTO_RAWCMDFRAME,
    PROTO_ROSSERIAL,
)


class SensorPayloadMixin:
    """Sensor devjson payload dispatch logic."""

    def _dispatch_sensor_payload(self, data: Dict):  # type: ignore[override]
        frame_id = self.get_parameter('frame_id').get_parameter_value().string_value
        self.get_logger().debug(f'Dispatching sensor payload: {data}')
        from .sensors.registry import get_decoder  # local import to avoid cycles
        for bus, devs in data.items():
            if not isinstance(devs, dict):
                continue
            for addr, pkt in devs.items():
                if not isinstance(pkt, dict):
                    continue
                tkey = pkt.get('_t', '')
                hex_data = pkt.get('x', '')
                dec = get_decoder(tkey, frame_id)
                if not dec or not hex_data:
                    continue
                for topic_suffix, ros_msg in dec.decode_samples(hex_data):
                    topic = f"{tkey}_{addr}/{topic_suffix}"
                    pub = self.publisher_cache.get(topic, type(ros_msg))
                    pub.publish(ros_msg)


class PublishMixin(SensorPayloadMixin):
    """Handling of publish frames arriving via dispatcher."""

    def _handle_publish_frame(self, frame: bytes):
        if len(frame) < 3:
            return
        msgnum, tprot = frame[0], frame[1]
        msg_type = (tprot >> 6) & 0x3
        proto = tprot & 0x3F

        # ROSSerial devjson publishes: payload is raw JSON (no element byte)
        if msg_type == TYPE_PUBLISH and proto == PROTO_ROSSERIAL:
            body = frame[2:]
            nul = body.find(b'\x00')
            if nul >= 0:
                body = body[:nul]
            try:
                obj = json.loads(body.decode('utf-8', errors='replace'))
                if isinstance(obj, dict):
                    self._dispatch_sensor_payload(obj)
            except Exception:
                self.get_logger().warn('Publish ROSSerial JSON decode failed')
            return

        # RAWCMDFRAME (RICJSON) publish → JSON (may be NUL-terminated)
        if msg_type == TYPE_PUBLISH and proto == PROTO_RAWCMDFRAME:
            body = frame[2:]
            nul = body.find(b'\x00')
            if nul >= 0:
                body = body[:nul]
            try:
                obj = json.loads(body.decode('utf-8', errors='replace'))
                if isinstance(obj, dict):
                    self._dispatch_sensor_payload(obj)
            except Exception:
                self.get_logger().warn('Publish RAWCMDFRAME JSON decode failed')
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
                except Exception:
                    self.get_logger().warn('Publish RICREST JSON decode failed')
            return

        self.get_logger().warn(
            f'Unhandled publish/report frame: type={(tprot >> 6) & 0x3} proto={proto} len={len(frame)}'
        )


class SerialMixin(SensorPayloadMixin):
    """Serial handling (mode detection, ASCII console, OverAscii/Hdlc)."""

    def _connect_serial(self):
        if self.state.connected:
            return True, 'Already connected'
        port = self.get_parameter('serial.port').value
        baud = int(self.get_parameter('serial.baud').value)
        timeout = float(self.get_parameter('serial.timeout').value)

        from .transports.serial import SerialTransport 

        st = SerialTransport(port=port, baud=baud, timeout=timeout)
        self.state.serial_transport = st

        st.on_status = self._on_serial_status
        st.on_bytes = self._serial_on_bytes

        self.get_logger().info(f'Opening serial: port={port} baud={baud} timeout={timeout}')
        st.start()
        self.state.uri = port
        return True, 'Connecting serial'

    # -------------------- RX path --------------------
    def _serial_on_bytes(self, raw: bytes):
        self.get_logger().debug(f'Serial RX: {raw}')
        if not raw:
            return
        if self._serial_debug:
            preview = ' '.join(f'{b:02X}' for b in raw[:64])
            self.get_logger().debug(f'Serial RX raw: {preview}' + (' …' if len(raw) > 64 else ''))

        # Decide mode if still auto
        if self._serial_mode == 'auto':
            high = sum(1 for b in raw if (b >= 0x80) or (b in (0x85, 0x8E, 0x8F)))
            printable = sum(1 for b in raw if (32 <= b < 127) or (b in (9, 10, 13)))
            if high > max(8, len(raw) // 4):
                self._serial_mode = 'overascii'
                self.get_logger().warn('Serial mode auto-detect: OVERASCII (RICSerial tunneled)')
            elif printable >= max(8, len(raw) // 2) and any(b in raw for b in (10, 13)):
                self._serial_mode = 'ascii'
                self.get_logger().warn('Serial mode auto-detect: ASCII CONSOLE')

        # Route depending on mode
        if self._serial_mode == 'overascii':
            self._oa.feed(raw)
        elif self._serial_mode == 'ascii':
            hb = bytes(b for b in raw if b & 0x80)
            lb = bytes(b for b in raw if not (b & 0x80))
            if hb:
                self._oa.feed(hb)
                if any(b in (0x85, 0x8E, 0x8F) or b & 0x80 for b in hb):
                    self._serial_mode = 'overascii'
                    self.get_logger().warn('Serial mode switched to OVERASCII after initial ASCII phase')
            if lb:
                self._feed_console(lb)
        else:  # Unknown forced mode → treat as ASCII console
            self._feed_console(raw)


    def _feed_console(self, raw: bytes):
        """
        Console handler:
        - Buffers incoming bytes
        - Opportunistically extracts balanced JSON objects (handles strings/escapes)
        - Emits any non-JSON text as console output
        - Dispatches parsed JSON to sensor/state pipeline
        - Optionally fulfills a waiting RPC event once per call
        """

        # ---------- Tunables ----------
        MAX_BUF = 65536
        TRIM_TO = 32768

        # ---------- Helpers ----------
        def append_and_trim(buf: bytearray, data: bytes) -> str:
            """Append to rolling buffer, trim if too large, return UTF-8 text view."""
            buf.extend(data)
            if len(buf) > MAX_BUF:
                # keep the newest part
                del buf[: len(buf) - TRIM_TO]
            return buf.decode('utf-8', errors='replace')

        def emit_console_text(chunk: str):
            """Log/publish plain console text (non-JSON)."""
            if not chunk:
                return
            # split to keep logs/topics tidy
            for line in chunk.splitlines():
                line = line.strip()
                if not line:
                    continue
                if getattr(self, "_serial_debug", False):
                    self.get_logger().debug(f'Console: {line}')
                else:
                    self.get_logger().info(f'Console: {line}')
                pub = getattr(self, "_console_pub", None)
                if pub:
                    from std_msgs.msg import String
                    pub.publish(String(data=line))

        def try_handle_json_fragment(js_text: str, rpc_consumed: bool) -> bool:
            """Parse JSON (best-effort), dispatch if dict, and fulfill RPC once.
            Returns updated rpc_consumed flag."""
            try:
                obj = json.loads(js_text)
            except Exception as ex:
                if getattr(self, "_serial_debug", False):
                    self.get_logger().debug(f'Console JSON parse skipped: {ex}')
                return rpc_consumed

            # fulfill waiting RPC once
            ev = getattr(self, "_console_wait_ev", None)
            if (ev is not None) and (not rpc_consumed):
                self._console_resp_buf = js_text.encode('utf-8')
                ev.set()
                rpc_consumed = True

            if getattr(self, "_serial_debug", False):
                self.get_logger().debug(f'Console JSON: {obj}')

            if isinstance(obj, dict) and obj:
                try:
                    self._dispatch_sensor_payload(obj)
                except Exception as ex:
                    self.get_logger().warn(f'Console JSON dispatch failed: {ex}')

            return rpc_consumed

        # ---------- Main flow ----------
        text = append_and_trim(self._console_buf, raw)
        emit_console_text(text)
        fragments = find_json_fragments(text)

        last = 0
        rpc_used = False

        for s, e in fragments:
            # plain text before this JSON
            if s > last:
                pass
                # emit_console_text(text[last:s])

            js = text[s:e]
            rpc_used = try_handle_json_fragment(js, rpc_used)
            last = e

        # Tail after the last JSON remains buffered (may be partial JSON or plain)
        tail = text[last:]
        self._console_buf = bytearray(tail.encode('utf-8', errors='replace'))
    # -------------------- Status / frames --------------------
    def _on_serial_status(self, connected: bool, msg: str):
        if connected:
            self.get_logger().info('Serial status: connected')
            self.state.connected = True
            self.state.last_error = ''
            if self.get_parameter('autosub').value:
                st = self.state.serial_transport
                if st is not None:
                    try:
                        rate = float(self.get_parameter('serial.devjson_rate_hz').value)
                        line = f'subscription?action=update&name=devjson&rateHz={rate}\n'
                        st.send(line.encode('utf-8'))
                        self.get_logger().info(f'Sent serial auto-subscription for devjson (rate {rate} Hz)')
                    except Exception as e:
                        self.get_logger().warn(f'Failed to send serial auto-subscription: {e}')
        else:
            self.state.connected = False
            if msg:
                self.state.last_error = msg
            self.get_logger().warn(f'Serial status: disconnected ({msg})')
            self._dispatcher.reset_waiters('serial status change')

    def _on_serial_frame(self, frame: bytes):
        if len(frame) >= 3:
            msgnum, tprot, elem0 = frame[0], frame[1], frame[2]
            mtype = (tprot >> 6) & 0x3
            proto = (tprot & 0x3F)
            self.get_logger().debug(
                f'Serial frame: msgnum={msgnum} type={mtype} proto={proto} elem={elem0 if len(frame)>2 else -1} len={len(frame)}'
            )
            from .ric_consts import (
                TYPE_PUBLISH, PROTO_ROSSERIAL, PROTO_RAWCMDFRAME, PROTO_RICREST, ELEM_CMDRESPJSON
            )
            if mtype == TYPE_PUBLISH:
                try:
                    if proto == PROTO_ROSSERIAL:
                        body = frame[2:]
                        nul = body.find(b'\x00')
                        body = body[:nul] if nul >= 0 else body
                        text = body.decode('utf-8', errors='replace')
                        data = json.loads(text)
                        self._dispatch_sensor_payload(data)
                        return
                    if proto == PROTO_RAWCMDFRAME:
                        body = frame[2:]
                        nul = body.find(b'\x00')
                        body = body[:nul] if nul >= 0 else body
                        text = body.decode('utf-8', errors='replace')
                        data = json.loads(text)
                        self._dispatch_sensor_payload(data)
                        return
                    elif proto == PROTO_RICREST and elem0 == ELEM_CMDRESPJSON:
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

        # Non publish → dispatcher handles RPC matching
        self._dispatcher.handle_frame(frame)


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
