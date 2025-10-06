
from __future__ import annotations

import json
import math
import struct
import threading
import time
from typing import Any, Dict, List, Optional



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
                self.get_logger().debug(
                    f"Dispatching {device_type}@{addr} on {bus_name} groups={list(segments)}"
                )
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

        tb_value = resp_meta.get('tb')
        ts_bytes = int(tb_value) if tb_value is not None else 0
        ts_fmt = resp_meta.get('tf') or '>H'
        wrap_mod = 1 << (ts_bytes * 8) if ts_bytes else 0
        chunk_bytes = sample_bytes + ts_bytes
        if chunk_bytes <= 0:
            return []

        self.get_logger().debug(
            f'Decode start {device_type}@{addr}: len={len(payload_bytes)} '
            f'sample_bytes={sample_bytes} ts_bytes={ts_bytes} chunk_bytes={chunk_bytes}'
        )

        samples: List[Dict[str, Any]] = []
        offset = 0
        key = (bus_name, addr, device_type)
        while offset + chunk_bytes <= len(payload_bytes):
            chunk = payload_bytes[offset : offset + chunk_bytes]
            self.get_logger().debug(
                f'Chunk {device_type}@{addr}: {chunk.hex()} offset={offset + chunk_bytes}'
            )
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
            else:
                payload = chunk

            values = self._decode_attribute_block(payload, attr_defs)
            self.get_logger().debug(
                f'Decoded sample {device_type}@{addr}: ts={ts_unwrapped} '
                f'values={json.dumps(values, default=str)}'
            )
            samples.append({'timestamp_ms': ts_unwrapped, 'values': values})

        if offset < len(payload_bytes):
            remainder = payload_bytes[offset:]
            if remainder:
                self.get_logger().debug(
                    f'Decode remainder {device_type}@{addr}: {remainder.hex()}'
                )

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
            self.get_logger().debug(
                f'Attr decoded {name}: raw={raw_bytes.hex()} fmt={fmt} '
                f'si={si_value} unit={attr.get("u")}'
            )
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
        self.get_logger().debug(f'Published generic {topic}: {msg.data}')

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
