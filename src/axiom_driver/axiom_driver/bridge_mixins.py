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
import math
import struct
import threading
import time
from typing import Any, Dict, List, Optional
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
        for bus_name, devs in data.items():
            if not isinstance(devs, dict):
                continue
            for addr, pkt in devs.items():
                if not isinstance(pkt, dict):
                    continue
                device_type = str(pkt.get('_t', '')).strip()
                if not device_type:
                    continue
                segments = self._extract_hex_segments(pkt)
                if not segments:
                    continue
                devinfo = self._get_device_typeinfo(bus_name, device_type)
                if not devinfo:
                    self.get_logger().debug(
                        f'No device type info yet for bus={bus_name} addr={addr} type={device_type}'
                    )
                    continue
                resp = devinfo.get('resp')
                if not isinstance(resp, dict) or not resp.get('a'):
                    self.get_logger().debug(
                        f'Device type info missing response metadata for bus={bus_name} type={device_type}'
                    )
                    continue

                for group_name, hex_data in segments.items():
                    samples = self._decode_samples_from_hex(
                        bus_name, addr, device_type, resp, hex_data
                    )
                    if not samples:
                        continue

                    for sample in samples:
                        try:
                            self._publish_generic_sample(bus_name, addr, device_type, group_name, sample)
                        except Exception as exc:  # noqa: BLE001
                            self.get_logger().warn(
                                f'Generic publish failed for {device_type}@{addr}: {exc}'
                            )
                        # try:
                        #     self._publish_specialized_sample(bus_name, addr, device_type, frame_id, sample, devinfo)
                        # except Exception as exc:  # noqa: BLE001
                        #     self.get_logger().debug(
                        #         f'Specialized publish skipped for {device_type}@{addr}: {exc}'
                        #     )

    # ----------- Firmware metadata helpers -----------

    def _extract_hex_segments(self, pkt: Dict[str, Any]) -> Dict[str, str]:
        segments: Dict[str, str] = {}
        for key, value in pkt.items():
            if key.startswith('_'):
                continue
            if isinstance(value, str) and value:
                segments[key] = value
        if not segments:
            hex_payload = pkt.get('x')
            if isinstance(hex_payload, str) and hex_payload:
                segments['x'] = hex_payload
        return segments

    def _get_device_typeinfo(self, bus_name: str, device_type: str) -> Optional[Dict[str, Any]]:
        key = (bus_name, device_type)
        lock = getattr(self, '_device_typeinfo_lock', None)
        if lock is None:
            self._device_typeinfo_lock = threading.Lock()
            self._device_typeinfo_cache = {}
            lock = self._device_typeinfo_lock
        if not hasattr(self, '_device_typeinfo_inflight'):
            self._device_typeinfo_inflight = set()

        retry_window = getattr(self, '_device_typeinfo_retry_window', 5.0)
        now = time.time()

        with lock:
            entry = self._device_typeinfo_cache.get(key)
            if entry and entry.get('info') is not None:
                return entry['info']
            if entry and entry.get('pending'):
                return None
            if entry and now - entry.get('ts', 0.0) < retry_window:
                return None

            if key in self._device_typeinfo_inflight:
                # Another worker is already fetching; mark as pending so we skip retries
                self._device_typeinfo_cache[key] = {'info': None, 'pending': True, 'ts': entry.get('ts', now) if entry else now}
                return None

            # Launch a background fetch
            self._device_typeinfo_inflight.add(key)
            self._device_typeinfo_cache[key] = {'info': None, 'pending': True, 'ts': now}

        def worker():
            try:
                self.get_logger().debug(f'[typeinfo] fetch start bus={bus_name} type={device_type}')
                info = self._request_device_typeinfo(bus_name, device_type)
                if info:
                    self.get_logger().debug(f'[typeinfo] fetch ok bus={bus_name} type={device_type}')
                else:
                    self.get_logger().debug(f'[typeinfo] fetch empty bus={bus_name} type={device_type}')
            except Exception as exc:  # noqa: BLE001
                self.get_logger().warn(f'Device type info fetch error bus={bus_name} type={device_type}: {exc}')
                info = None
            finally:
                with lock:
                    self._device_typeinfo_inflight.discard(key)
                    self._device_typeinfo_cache[key] = {
                        'info': info,
                        'pending': False,
                        'ts': time.time(),
                    }

        threading.Thread(target=worker, daemon=True, name=f'typeinfo-{bus_name}-{device_type}').start()
        return None

    def _request_device_typeinfo(self, bus_name: str, device_type: str) -> Optional[Dict[str, Any]]:
        path = f'devman/typeinfo?bus={bus_name}&type={device_type}'
        timeout = getattr(self, '_device_typeinfo_request_timeout', 2.0)
        data = self._ric_rest_json(path, timeout=timeout)
        if not isinstance(data, dict):
            return None
        rslt = data.get('rslt')
        if isinstance(rslt, str) and rslt.lower() not in ('ok', 'success'):
            self.get_logger().debug(
                f'Device type info request failed for bus={bus_name} type={device_type}: rslt={rslt}'
            )
            return None
        devinfo = data.get('devinfo') or data.get('deviceTypeInfo') or data.get('info')
        if devinfo is None and 'rslt' not in data:
            devinfo = data
        return devinfo if isinstance(devinfo, dict) else None

    def _ric_rest_json(self, url_path: str, timeout: Optional[float] = None):
        try:
            success, message, payload = self._send_ric_rest_url(url_path, timeout=timeout)
        except AttributeError:
            self.get_logger().warn('RIC REST helper not available on this node')
            return None

        if not success:
            if message in ('Not connected', 'Serial transport not started'):
                self.get_logger().debug(f'RICREST request deferred ({message}): {url_path}')
            else:
                self.get_logger().warn(f'RICREST request failed for {url_path}: {message}')
            return None

        if not payload:
            return {}

        try:
            text = payload.decode('utf-8', errors='replace')
            return json.loads(text)
        except Exception as exc:  # noqa: BLE001
            self.get_logger().warn(f'RICREST JSON decode failed for {url_path}: {exc}')
            return None

    # ----------- Sample decoding -----------

    def _decode_samples_from_hex(
        self,
        bus_name: str,
        addr: str,
        device_type: str,
        resp_meta: Dict[str, Any],
        hex_data: str,
    ) -> List[Dict[str, Any]]:
        try:
            payload_bytes = bytes.fromhex(hex_data)
        except Exception:
            self.get_logger().warn(f'Invalid hex payload for {device_type}@{addr}')
            return []

        attr_defs = resp_meta.get('a') or []
        if not isinstance(attr_defs, list) or not attr_defs:
            return []

        sample_bytes = int(resp_meta.get('b') or 0)
        if sample_bytes <= 0:
            sample_bytes = 0
            for attr in attr_defs:
                fmt = attr.get('t')
                if fmt:
                    try:
                        sample_bytes += struct.calcsize(fmt)
                    except Exception:
                        pass

        ts_bytes = int(resp_meta.get('tb') or 2)
        ts_fmt = resp_meta.get('tf') or '>H'
        wrap_mod = 1 << (ts_bytes * 8) if ts_bytes > 0 else 0
        chunk_bytes = sample_bytes + ts_bytes
        if chunk_bytes <= 0:
            return []

        samples: List[Dict[str, Any]] = []
        offset = 0
        key = (bus_name, addr, device_type)
        while offset + chunk_bytes <= len(payload_bytes):
            chunk = payload_bytes[offset : offset + chunk_bytes]
            offset += chunk_bytes

            ts_wrapped = 0
            ts_unwrapped = None
            payload = chunk
            if ts_bytes:
                ts_part = chunk[:ts_bytes]
                payload = chunk[ts_bytes:]
                try:
                    ts_tuple = struct.unpack(ts_fmt, ts_part)
                    ts_wrapped = ts_tuple[0] if ts_tuple else 0
                except Exception:
                    ts_wrapped = int.from_bytes(ts_part, 'big')
                if wrap_mod:
                    ts_unwrapped = self._unwrap_device_timestamp(key, ts_wrapped, wrap_mod)

            values = self._decode_attribute_block(payload, attr_defs)
            samples.append({'timestamp_ms': ts_unwrapped, 'values': values})

        return samples

    def _unwrap_device_timestamp(self, key, ts_wrapped: int, wrap_mod: int) -> int:
        state = getattr(self, '_device_ts_state', None)
        if state is None:
            self._device_ts_state = {}
            state = self._device_ts_state
        last, offset = state.get(key, (0, 0))
        if ts_wrapped < last:
            offset += wrap_mod
        state[key] = (ts_wrapped, offset)
        return offset + ts_wrapped

    def _decode_attribute_block(self, payload: bytes, attr_defs: List[Dict[str, Any]]):
        cursor = 0
        results: Dict[str, Dict[str, Any]] = {}
        for attr in attr_defs:
            fmt = attr.get('t')
            name = attr.get('n') or f'field_{cursor}'
            if not fmt:
                continue
            try:
                size = struct.calcsize(fmt)
            except Exception:
                continue
            if cursor + size > len(payload):
                break
            raw_bytes = payload[cursor : cursor + size]
            cursor += size
            try:
                raw_value = struct.unpack(fmt, raw_bytes)
            except Exception:
                continue
            value = raw_value if len(raw_value) > 1 else raw_value[0]
            processed = self._post_process_value(value, attr)
            si_value, si_unit = self._to_si_units(processed, attr.get('u'))
            results[name] = {
                'value': processed,
                'unit': attr.get('u'),
                'si_value': si_value,
                'si_unit': si_unit,
                'raw': value,
                'meta': attr,
            }
        return results

    def _post_process_value(self, value: Any, attr: Dict[str, Any]) -> Any:
        if isinstance(value, tuple):
            value = list(value)

        if isinstance(value, int):
            mask = self._parse_numeric(attr.get('m'))
            xor = self._parse_numeric(attr.get('x'))
            if mask is not None:
                xor_val = xor or 0
                value = (value ^ int(xor_val)) & int(mask)
            shift = self._parse_numeric(attr.get('s'))
            if shift:
                value = value >> int(shift)

        divisor = attr.get('d')
        if divisor:
            try:
                divisor = float(divisor)
                if divisor:
                    if isinstance(value, list):
                        value = [v / divisor for v in value]
                    else:
                        value = value / divisor
            except Exception:
                pass

        output = str(attr.get('o') or '').lower()
        if output == 'bool':
            value = bool(value)
        elif output in ('float', 'double'):
            if isinstance(value, list):
                value = [float(v) for v in value]
            else:
                value = float(value)
        elif output.startswith('uint') or output.startswith('int'):
            if isinstance(value, list):
                value = [int(v) for v in value]
            else:
                value = int(value)

        return value

    def _parse_numeric(self, value: Any):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                if text.lower().startswith('0x'):
                    return int(text, 16)
                return int(text)
            except ValueError:
                try:
                    return float(text)
                except ValueError:
                    return None
        return None

    _SI_CONVERSIONS = {
        '&deg;/s': ('rad/s', lambda v: float(v) * math.pi / 180.0),
        'deg/s': ('rad/s', lambda v: float(v) * math.pi / 180.0),
        '°/s': ('rad/s', lambda v: float(v) * math.pi / 180.0),
        '&deg;': ('rad', lambda v: float(v) * math.pi / 180.0),
        'deg': ('rad', lambda v: float(v) * math.pi / 180.0),
        'g': ('m/s^2', lambda v: float(v) * 9.80665),
        'mm': ('m', lambda v: float(v) / 1000.0),
        'cm': ('m', lambda v: float(v) / 100.0),
        '%': ('fraction', lambda v: float(v) / 100.0),
    }

    def _to_si_units(self, value: Any, unit: Optional[str]):
        if unit is None:
            return None, None
        key = unit.strip()
        conversion = self._SI_CONVERSIONS.get(key)
        if not conversion:
            return None, None
        si_unit, func = conversion
        try:
            if isinstance(value, list):
                return [func(v) for v in value], si_unit
            return func(value), si_unit
        except Exception:
            return None, None

    # ----------- Publishing helpers -----------

    def _publish_generic_sample(
        self,
        bus_name: str,
        addr: str,
        device_type: str,
        group_name: str,
        sample: Dict[str, Any],
    ):
        from std_msgs.msg import String  # local import

        values_block = {}
        for name, entry in sample['values'].items():
            values_block[name] = {
                'value': entry.get('value'),
                'unit': entry.get('unit'),
                'si_value': entry.get('si_value'),
                'si_unit': entry.get('si_unit'),
            }
        payload = {
            'bus': bus_name,
            'address': addr,
            'type': device_type,
            'group': group_name,
            'timestamp_ms': sample.get('timestamp_ms'),
            'values': values_block,
        }
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
        topic = f'{device_type}_{addr}/data'
        pub = self.publisher_cache.get(topic, String)
        pub.publish(msg)

    def _publish_specialized_sample(
        self,
        bus_name: str,
        addr: str,
        device_type: str,
        frame_id: str,
        sample: Dict[str, Any],
        devinfo: Dict[str, Any],
    ):
        dtype = device_type.upper()
        values = sample['values']

        if dtype == 'LSM6DS':
            required = ['gx', 'gy', 'gz', 'ax', 'ay', 'az']
            if not all(name in values for name in required):
                return
            try:
                from axiom_interfaces.msg import Imu6
            except ImportError:
                self.get_logger().warn('Imu6 message type not available')
                return
            msg = Imu6()
            msg.header.frame_id = frame_id
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.gx = float(self._select_si(values['gx']))
            msg.gy = float(self._select_si(values['gy']))
            msg.gz = float(self._select_si(values['gz']))
            msg.ax = float(self._select_si(values['ax']))
            msg.ay = float(self._select_si(values['ay']))
            msg.az = float(self._select_si(values['az']))
            topic = f'{device_type}_{addr}/imu/data_raw'
            pub = self.publisher_cache.get(topic, Imu6)
            pub.publish(msg)
            return

        if dtype in ('VL53L4CD', 'VL53', 'DIST'):
            dist_entry = values.get('dist') or values.get('distance')
            if not dist_entry:
                return
            valid_entry = values.get('valid')
            if valid_entry is not None and not bool(valid_entry.get('value')):
                return
            try:
                from sensor_msgs.msg import Range
            except ImportError:
                self.get_logger().warn('sensor_msgs/Range not available')
                return
            msg = Range()
            msg.header.frame_id = frame_id
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.radiation_type = Range.INFRARED
            msg.range = float(self._select_si(dist_entry))
            min_range, max_range = self._range_limits_si(dist_entry)
            msg.min_range = min_range
            msg.max_range = max_range
            msg.field_of_view = math.nan
            topic = f'{device_type}_{addr}/range/front'
            pub = self.publisher_cache.get(topic, Range)
            pub.publish(msg)
            return

        if dtype == 'AHT20':
            temp_entry = (
                values.get('temperature')
                or values.get('temp')
                or values.get('tempC')
                or values.get('t')
            )
            humid_entry = (
                values.get('humidity')
                or values.get('humid')
                or values.get('rh')
            )
            if temp_entry:
                try:
                    from sensor_msgs.msg import Temperature
                except ImportError:
                    self.get_logger().warn('sensor_msgs/Temperature not available')
                    temp_entry = None
                else:
                    msg = Temperature()
                    msg.header.frame_id = frame_id
                    msg.header.stamp = self.get_clock().now().to_msg()
                    msg.temperature = float(self._select_si(temp_entry))
                    msg.variance = 0.0
                    topic = f'{device_type}_{addr}/environment/temperature'
                    pub = self.publisher_cache.get(topic, Temperature)
                    pub.publish(msg)
            if humid_entry:
                try:
                    from sensor_msgs.msg import RelativeHumidity
                except ImportError:
                    self.get_logger().warn('sensor_msgs/RelativeHumidity not available')
                    return
                msg = RelativeHumidity()
                msg.header.frame_id = frame_id
                msg.header.stamp = self.get_clock().now().to_msg()
                msg.relative_humidity = float(self._select_si(humid_entry))
                msg.variance = 0.0
                topic = f'{device_type}_{addr}/environment/humidity'
                pub = self.publisher_cache.get(topic, RelativeHumidity)
                pub.publish(msg)

    def _select_si(self, entry: Dict[str, Any]) -> float:
        si_val = entry.get('si_value')
        if si_val is not None:
            return float(si_val)
        return float(entry.get('value', 0.0))

    def _range_limits_si(self, entry: Dict[str, Any]):
        meta = entry.get('meta') or {}
        rng = meta.get('r')
        if not isinstance(rng, (list, tuple)) or len(rng) != 2:
            return 0.0, 0.0
        try:
            lo, hi = float(rng[0]), float(rng[1])
        except Exception:
            return 0.0, 0.0
        unit = entry.get('unit')
        conversion = self._SI_CONVERSIONS.get(unit.strip()) if isinstance(unit, str) else None
        if conversion:
            _, func = conversion
            try:
                return float(func(lo)), float(func(hi))
            except Exception:
                pass
        return lo, hi


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
