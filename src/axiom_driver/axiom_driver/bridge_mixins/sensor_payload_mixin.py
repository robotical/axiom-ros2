
from __future__ import annotations

import json
import math
import struct
import threading
import time
from typing import Any, Dict, List, Optional

from .attr_decoder import AttrBlockDecoder
from .custom_attr_handler import CustomAttrHandler


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
                        try:
                            self._publish_specialized_sample(bus_name, addr, device_type, frame_id, sample, devinfo)
                        except Exception as exc:  # noqa: BLE001
                            self.get_logger().debug(
                                f'Specialized publish skipped for {device_type}@{addr}: {exc}'
                            )

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
        self.get_logger().info(f'Device type info response for bus={bus_name} type={device_type}: {json.dumps(data, separators=(",", ":"))}')
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

    def _get_attr_decoder(self) -> AttrBlockDecoder:
        decoder = getattr(self, '_attr_block_decoder', None)
        if decoder is None:
            decoder = AttrBlockDecoder()
            self._attr_block_decoder = decoder
        return decoder

    def _get_custom_attr_handler(self) -> CustomAttrHandler:
        handler = getattr(self, '_custom_attr_handler', None)
        if handler is None:
            handler = CustomAttrHandler()
            self._custom_attr_handler = handler
        return handler

    def _infer_timestamp_size(self, sample_bytes: int, payload_len: int) -> int:
        if sample_bytes <= 0 or payload_len <= 0:
            return 0

        # Prefer the standard 2-byte timestamp used by the JS implementation
        candidate_sizes = (2, 4, 6, 8, 0)
        for candidate in candidate_sizes:
            chunk = sample_bytes + candidate
            if chunk <= 0:
                continue
            if payload_len >= chunk and payload_len % chunk == 0:
                return candidate

        if payload_len >= sample_bytes + 2:
            return 2

        return 0

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

        payload_len = len(payload_bytes)

        ts_value = resp_meta.get('tb')
        if ts_value is None:
            ts_bytes = self._infer_timestamp_size(sample_bytes, payload_len)
        else:
            try:
                ts_bytes = int(ts_value)
            except Exception:
                ts_bytes = 0
        if ts_bytes < 0:
            ts_bytes = 0

        resolution_field = resp_meta.get('tr') or resp_meta.get('timestamp_resolution_us')
        try:
            resolution_us = int(resolution_field) if resolution_field is not None else 1000
        except Exception:
            resolution_us = 1000
        if ts_bytes == 0:
            resolution_us = 0

        ts_fmt = resp_meta.get('tf')
        if ts_bytes:
            if not ts_fmt:
                default_ts_fmt = {
                    1: '>B',
                    2: '>H',
                    3: '>3s',
                    4: '>I',
                    6: '>6s',
                    8: '>Q',
                }
                ts_fmt = default_ts_fmt.get(ts_bytes, f'>{ts_bytes}s')
        else:
            ts_fmt = None

        wrap_mod = (1 << (ts_bytes * 8)) if ts_bytes else 0
        chunk_bytes = sample_bytes + ts_bytes
        if chunk_bytes <= 0:
            return []

        self.get_logger().debug(
            f'Decode start {device_type}@{addr}: len={payload_len} '
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
            timestamp_us = None
            payload = chunk
            if ts_bytes and ts_fmt:
                ts_part = chunk[:ts_bytes]
                payload = chunk[ts_bytes:]
                try:
                    ts_tuple = struct.unpack(ts_fmt, ts_part)
                    raw_component = ts_tuple[0] if ts_tuple else 0
                    if isinstance(raw_component, (bytes, bytearray)):
                        ts_wrapped = int.from_bytes(raw_component, 'big')
                    else:
                        ts_wrapped = int(raw_component)
                except Exception:
                    ts_wrapped = int.from_bytes(ts_part, 'big')
                timestamp_us = self._unwrap_device_timestamp(
                    key,
                    ts_wrapped,
                    wrap_mod,
                    resolution_us,
                )
            else:
                payload = chunk

            if resp_meta.get('c'):
                values = self._decode_custom_attribute_block(payload, resp_meta)
            else:
                values = self._decode_attribute_block(payload, attr_defs)
            ts_ms = None
            if timestamp_us is not None:
                ts_ms = timestamp_us / 1000.0
            self.get_logger().debug(
                f'Decoded sample {device_type}@{addr}: ts_us={timestamp_us} '
                f'values={json.dumps(values, default=str)}'
            )
            sample_entry = {'timestamp_ms': ts_ms, 'values': values}
            if timestamp_us is not None:
                sample_entry['timestamp_us'] = timestamp_us
            samples.append(sample_entry)

        if offset < len(payload_bytes):
            remainder = payload_bytes[offset:]
            if remainder:
                self.get_logger().debug(
                    f'Decode remainder {device_type}@{addr}: {remainder.hex()}'
                )

        return samples

    def _unwrap_device_timestamp(
        self,
        key,
        ts_wrapped: int,
        wrap_mod: int,
        resolution_us: int,
    ) -> int:
        state = getattr(self, '_device_ts_state', None)
        if state is None:
            self._device_ts_state = {}
            state = self._device_ts_state

        entry = state.get(key)
        if not isinstance(entry, dict):
            if isinstance(entry, tuple) and len(entry) == 2:
                last_raw, raw_offset = entry
                offset_us = raw_offset * (resolution_us or 1)
                entry = {
                    'last_base_us': last_raw * (resolution_us or 1),
                    'offset_us': offset_us,
                    'last_raw': last_raw,
                }
            else:
                entry = {'last_base_us': None, 'offset_us': 0, 'last_raw': None}

        base_us = ts_wrapped * resolution_us if resolution_us else ts_wrapped
        last_base_us = entry.get('last_base_us')
        offset_us = entry.get('offset_us', 0)

        if wrap_mod:
            if resolution_us:
                # Treat a backwards jump greater than 100 ms as a wrap event (matches JS logic)
                threshold_us = 100_000
                if last_base_us is not None and base_us + threshold_us < last_base_us:
                    offset_us += wrap_mod * resolution_us
            else:
                last_raw = entry.get('last_raw')
                if last_raw is not None and ts_wrapped < last_raw:
                    offset_us += wrap_mod

        entry['last_base_us'] = base_us
        entry['offset_us'] = offset_us
        entry['last_raw'] = ts_wrapped
        state[key] = entry
        return base_us + offset_us

    def _decode_attribute_block(self, payload: bytes, attr_defs: List[Dict[str, Any]]):
        logger = self.get_logger()
        decoder = self._get_attr_decoder()
        decoded_attrs = decoder.decode_block(payload, attr_defs, logger=logger)

        results: Dict[str, Dict[str, Any]] = {}
        for entry in decoded_attrs:
            processed = self._post_process_value(entry.value, entry.meta)
            si_value, si_unit = self._to_si_units(processed, entry.meta.get('u'))
            results[entry.name] = {
                'value': processed,
                'unit': entry.meta.get('u'),
                'si_value': si_value,
                'si_unit': si_unit,
                'raw': entry.raw_value,
                'meta': entry.meta,
            }
            logger.debug(
                f'Attr decoded {entry.name}: raw={entry.raw_bytes.hex()} fmt={entry.meta.get("t")} '
                f'si={si_value} unit={entry.meta.get("u")}'
            )
        self._apply_validation_links(attr_defs, results)
        return results

    def _apply_validation_links(
        self,
        attr_defs: List[Dict[str, Any]],
        results: Dict[str, Dict[str, Any]],
    ) -> None:
        for attr in attr_defs:
            validator_name = attr.get('vft')
            target_name = attr.get('n')
            if not validator_name or not target_name:
                continue
            target_entry = results.get(target_name)
            validator_entry = results.get(validator_name)
            if not target_entry or not validator_entry:
                continue

            validator_value = validator_entry.get('value')
            validator_series = (
                list(validator_value)
                if isinstance(validator_value, list)
                else [validator_value]
            )
            validator_flags = [bool(v) for v in validator_series]

            target_value = target_entry.get('value')
            target_series = (
                list(target_value)
                if isinstance(target_value, list)
                else [target_value]
            )
            target_si = target_entry.get('si_value')
            target_si_series = (
                list(target_si)
                if isinstance(target_si, list)
                else [target_si]
            )

            changed = False
            count = min(len(target_series), len(validator_flags))
            for idx in range(count):
                if not validator_flags[idx]:
                    target_series[idx] = math.nan
                    if idx < len(target_si_series):
                        target_si_series[idx] = math.nan
                    changed = True

            if not changed:
                continue

            if isinstance(target_value, list):
                target_entry['value'] = target_series
            else:
                target_entry['value'] = target_series[0]

            if isinstance(target_si, list):
                target_entry['si_value'] = target_si_series
            else:
                target_entry['si_value'] = target_si_series[0]

    def _decode_custom_attribute_block(
        self,
        payload: bytes,
        resp_meta: Dict[str, Any],
    ) -> Dict[str, Dict[str, Any]]:
        handler = self._get_custom_attr_handler()
        attr_values = handler.handle_attr(resp_meta, payload)
        if not attr_values:
            return {}

        attr_defs = resp_meta.get('a') or []
        results: Dict[str, Dict[str, Any]] = {}

        for attr in attr_defs:
            name = attr.get('n')
            if not name:
                continue

            raw_values = attr_values.get(name, [])
            if isinstance(raw_values, list):
                raw_collapsed: Any
                if len(raw_values) == 1:
                    raw_collapsed = raw_values[0]
                else:
                    raw_collapsed = list(raw_values)
            else:
                raw_collapsed = raw_values

            processed = self._post_process_value(raw_collapsed, attr)
            si_value, si_unit = self._to_si_units(processed, attr.get('u'))

            results[name] = {
                'value': processed,
                'unit': attr.get('u'),
                'si_value': si_value,
                'si_unit': si_unit,
                'raw': raw_collapsed,
                'meta': attr,
            }

        self._apply_validation_links(attr_defs, results)
        return results

    def _post_process_value(self, value: Any, attr: Dict[str, Any]) -> Any:
        if isinstance(value, tuple):
            value = list(value)

        output = str(attr.get('o') or '').lower()
        if output == 'bool':
            if isinstance(value, list):
                return [bool(v) for v in value]
            return bool(value)
        if output in ('float', 'double'):
            if isinstance(value, list):
                try:
                    return [float(v) for v in value]
                except Exception:
                    return value
            try:
                return float(value)
            except Exception:
                return value
        if output.startswith('uint') or output.startswith('int'):
            if isinstance(value, list):
                try:
                    return [int(v) for v in value]
                except Exception:
                    return value
            try:
                return int(value)
            except Exception:
                return value

        return value

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

        if dtype == 'VL53L4CD':
            dist_entry = values.get('dist') or values.get('distance')
            if not dist_entry:
                return

            # Check validity flag (if present)
            valid_entry = values.get('valid')
            if valid_entry is not None and not bool(valid_entry.get('value')):
                # Still publish custom msg with valid=false if you want visibility,
                # or early-return to suppress any output on invalid.
                # Here we continue and mark valid=false.
                is_valid = bool(valid_entry.get('value'))
            else:
                is_valid = True

            # Pull SI (meters) and raw (mm) if available
            def pick(entry, key):
                return entry.get(key) if entry is not None else None

            si_m = pick(dist_entry, 'si_value')
            raw_mm = pick(dist_entry, 'value')
            if si_m is None and raw_mm is None:
                return

            try:
                from axiom_interfaces.msg import VL53L4CDReading
            except ImportError:
                self.get_logger().warn('VL53L4CDReading message type not available')
                return

            # --- Publish custom reading ---
            msg_raw = VL53L4CDReading()
            msg_raw.header.frame_id = frame_id
            msg_raw.header.stamp = self.get_clock().now().to_msg()
            msg_raw.valid = bool(is_valid)
            if si_m is not None:
                msg_raw.distance_m = float(si_m)
            elif raw_mm is not None:
                msg_raw.distance_m = float(raw_mm) / 1000.0
            else:
                msg_raw.distance_m = float('nan')

            msg_raw.distance_mm = int(raw_mm) if raw_mm is not None else 0

            topic_raw = f'{device_type}_{addr}/range/raw'
            pub_raw = self.publisher_cache.get(topic_raw, VL53L4CDReading)
            pub_raw.publish(msg_raw)

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

        if dtype == 'AMG8833':
            temp_attr_name = None
            temp_entry: Optional[Dict[str, Any]] = None
            for candidate in ('temp', 'temperature', 'tempC', 't'):
                entry = values.get(candidate)
                if entry:
                    temp_attr_name = candidate
                    temp_entry = entry
                    break

            if not temp_entry or not temp_attr_name:
                return

            temps = self._extract_numeric_series(temp_entry)

            if not temps:
                return

            temps = self._convert_series_to_celsius(temps, temp_entry.get('unit'))

            width, height = self._resolve_thermal_dimensions(
                temp_attr_name,
                temp_entry,
                devinfo,
                len(temps),
            )

            if width <= 0 or height <= 0:
                width = len(temps)
                height = 1

            if width * height != len(temps):
                self.get_logger().debug(
                    f'AMG8833 grid mismatch len={len(temps)} width={width} height={height}; flattening row'
                )
                width = len(temps)
                height = 1

            try:
                from axiom_interfaces.msg import ThermalGrid
            except ImportError:
                self.get_logger().warn('ThermalGrid message type not available')
                return

            msg = ThermalGrid()
            msg.header.frame_id = frame_id
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.width = int(width)
            msg.height = int(height)
            msg.temperature_c = [float(v) for v in temps]

            topic = f'{device_type}_{addr}/thermal/grid'
            pub = self.publisher_cache.get(topic, ThermalGrid)
            pub.publish(msg)
            return

        if dtype == 'AXIOMPOWERV1':
            try:
                from axiom_interfaces.msg import AxiomPowerState
            except ImportError:
                self.get_logger().warn('AxiomPowerState message type not available')
                return

            # helper to get numeric/boolean from your {value, unit, si_value, si_unit} dicts
            def pick(entry, cast):
                if entry is None:
                    return None
                # prefer si_value if present
                v = entry.get('si_value')
                if v is None:
                    v = entry.get('value')
                try:
                    return cast(v)
                except Exception:
                    return None

            batt_v = pick(values.get('battV'), float)

            # Require at least voltage; others can be optional
            if batt_v is None:
                return

            msg = AxiomPowerState()
            msg.header.frame_id = frame_id
            msg.header.stamp = self.get_clock().now().to_msg()
            msg.batt_v = float(batt_v)

            topic = f'{device_type}_{addr}/power/state'
            pub = self.publisher_cache.get(topic, AxiomPowerState)
            pub.publish(msg)
            return

    def _extract_numeric_series(self, entry: Dict[str, Any]) -> List[float]:
        if not isinstance(entry, dict):
            return []

        for key in ('si_value', 'value', 'raw'):
            series = entry.get(key)
            values = self._coerce_float_list(series)
            if values:
                return values
        return []

    def _coerce_float_list(self, series: Any) -> List[float]:
        if isinstance(series, (list, tuple)):
            result: List[float] = []
            for item in series:
                try:
                    result.append(float(item))
                except (TypeError, ValueError):
                    continue
            return result
        if series is None:
            return []
        try:
            return [float(series)]
        except (TypeError, ValueError):
            return []

    def _convert_series_to_celsius(self, series: List[float], unit: Any) -> List[float]:
        if not series:
            return []
        if not isinstance(unit, str):
            return series

        normalized = unit.replace('&deg;', '°').strip().lower()
        if not normalized or normalized in {'°c', 'c', 'celsius', 'degc'}:
            return series
        if normalized in {'°f', 'f', 'fahrenheit', 'degf'}:
            return [(val - 32.0) * (5.0 / 9.0) for val in series]
        if normalized in {'k', 'kelvin'}:
            return [val - 273.15 for val in series]
        return series

    def _resolve_thermal_dimensions(
        self,
        attr_name: str,
        entry: Dict[str, Any],
        devinfo: Optional[Dict[str, Any]],
        sample_len: int,
    ) -> tuple[int, int]:
        meta_candidates: List[Dict[str, Any]] = []
        if isinstance(entry.get('meta'), dict):
            meta_candidates.append(entry['meta'])

        if isinstance(devinfo, dict):
            resp = devinfo.get('resp')
            if isinstance(resp, dict):
                attr_defs = resp.get('a')
                if isinstance(attr_defs, list):
                    for attr in attr_defs:
                        if not isinstance(attr, dict):
                            continue
                        if attr.get('n') == attr_name:
                            meta_candidates.append(attr)
                            break

        for meta in meta_candidates:
            width, height = self._parse_resolution_spec(meta.get('resolution') or meta.get('res'))
            if width > 0 and height > 0:
                return width, height

        if sample_len > 0:
            side = int(math.isqrt(sample_len))
            if side * side == sample_len:
                return side, side

        return 0, 0

    def _parse_resolution_spec(self, spec: Any) -> tuple[int, int]:
        if not isinstance(spec, str):
            return 0, 0
        text = spec.replace('×', 'x').lower()
        if 'x' not in text:
            return 0, 0
        left, right = text.split('x', 1)
        try:
            width = int(left.strip())
            height = int(right.strip())
        except ValueError:
            return 0, 0
        return width, height

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
