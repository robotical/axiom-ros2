
from __future__ import annotations

import json

from ..utils.string import find_json_fragments

from ..bridge_mixins.sensor_payload_mixin import SensorPayloadMixin

class SerialMixin(SensorPayloadMixin):
    """Serial handling (mode detection, ASCII console, OverAscii/Hdlc)."""

    def _connect_serial(self):
        if self.state.connected:
            return True, 'Already connected'
        port = self.get_parameter('serial.port').value
        baud = int(self.get_parameter('serial.baud').value)
        timeout = float(self.get_parameter('serial.timeout').value)

        from ..transports.serial import SerialTransport 

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
                self.get_logger().debug(f"Publish payload: {json.dumps(obj, separators=(',', ':'))}")
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
            from ..ric_consts import (
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
