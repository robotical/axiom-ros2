"""Decode firmware poll blocks without transport or ROS dependencies."""

import math

from .attributes import AttrBlockDecoder
from .custom import decode_custom, DecodeError
from .units import to_si


class SampleDecoder:
    """Separate poll framing, scalar/vector attributes, and FIFO sample rows."""

    def __init__(self):
        self.attributes = AttrBlockDecoder()

    def blocks(self, hex_data, metadata, device_type=''):
        """Return (raw counter, decoded rows, overflow) for each devjson poll."""
        try:
            payload = bytes.fromhex(hex_data)
            size = int(metadata['b'])
            timestamp_bytes = int(metadata.get('tb', 2))
        except (ValueError, TypeError, KeyError) as exc:
            raise DecodeError(f'Invalid poll framing: {exc}') from exc
        if not 0 < size <= 65536 or timestamp_bytes not in (0, 1, 2, 4, 8):
            raise DecodeError('Unsupported poll size/timestamp width')
        stride = size + timestamp_bytes
        if len(payload) % stride:
            raise DecodeError(f'Truncated poll stream: {len(payload)} bytes, stride {stride}')
        result = []
        for start in range(0, len(payload), stride):
            tick = int.from_bytes(payload[start: start + timestamp_bytes], 'big')
            block = payload[start + timestamp_bytes: start + stride]
            rows, overflow = self.values(block, metadata, device_type)
            result.append((tick if timestamp_bytes else None, rows, overflow))
        return result

    def values(self, payload, metadata, device_type=''):
        attrs = metadata.get('a')
        if not isinstance(attrs, list) or not attrs or len(attrs) > 256:
            raise DecodeError('Response attributes missing or exceed limit')
        names = [a.get('n') for a in attrs]
        if any(not isinstance(n, str) or not n for n in names) or len(set(names)) != len(names):
            raise DecodeError('Invalid/duplicate attribute names')
        overflow = 0
        if metadata.get('c'):
            result = decode_custom(payload, metadata)
            overflow = result.overflow
            rows = []
            for raw_row in result.rows:
                row = {}
                for attr in attrs:
                    name = attr['n']
                    if name not in raw_row:
                        raise DecodeError(f'Missing custom attribute: {name}')
                    raw = raw_row[name]
                    value = raw
                    if not result.engineering:
                        # Built-ins return signed raw scalars, then use the same
                        # mask/shift/divisor/offset/LUT rules as ordinary records.
                        value = self.attributes._apply_operations(
                            [raw],
                            attr,
                            'm' in attr and self.attributes._is_format_signed(attr.get('t', '')),
                            self.attributes._infer_item_width(attr.get('t', '')),
                        )[0]
                    row[name] = self.entry(raw, value, attr, device_type)
                rows.append(row)
        else:
            decoded = self.attributes.decode_block(payload, attrs)
            if len(decoded) != len(attrs):
                raise DecodeError('Attribute schema does not fit response block')
            rows = [
                {a.name: self.entry(a.raw_value, a.value, a.meta, device_type) for a in decoded}
            ]
        for row in rows:
            self.validate(row, attrs)
        return rows, overflow

    @staticmethod
    def entry(raw, value, attr, device_type):
        # `o` is the firmware's generated storage type, not an instruction to
        # truncate engineering values after applying a divisor/offset.
        if attr.get('o') == 'bool':
            value = [bool(v) for v in value] if isinstance(value, list) else bool(value)
        if isinstance(value, bytes):
            value = value.rstrip(b'\0').decode('utf-8', errors='replace')
        if isinstance(raw, bytes):
            raw = raw.hex()
        si_value, si_unit = to_si(
            value, attr.get('u'), attribute=attr['n'], device_type=device_type
        )
        return {
            'raw': raw,
            'value': value,
            'unit': attr.get('u'),
            'si_value': si_value,
            'si_unit': si_unit,
            'valid': True,
            'meta': attr,
        }

    @staticmethod
    def validate(row, attrs):
        for attr in attrs:
            validator = attr.get('vft')
            if not validator:
                continue
            if validator not in row:
                raise DecodeError(f'Unknown validation attribute: {validator}')
            target = row[attr['n']]
            flags = row[validator]['value']
            if isinstance(target['value'], list):
                if not isinstance(flags, list):
                    flags = [flags] * len(target['value'])
                if len(flags) != len(target['value']):
                    raise DecodeError('Validation vector length mismatch')
                target['valid'] = [bool(f) for f in flags]
                target['value'] = [v if f else math.nan for v, f in zip(target['value'], flags)]
                if isinstance(target['si_value'], list):
                    target['si_value'] = [
                        v if f else math.nan for v, f in zip(target['si_value'], flags)
                    ]
            elif not flags:
                target['valid'] = False
                target['value'] = math.nan
                if target['si_value'] is not None:
                    target['si_value'] = math.nan
