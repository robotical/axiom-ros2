"""Firmware attribute layouts and engineering transforms."""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
import struct
from typing import Any, Dict, Iterable, List, Optional, Sequence

SIGNED_FORMAT_CHARS = {'b', 'h', 'i', 'l', 'q'}
UNSIGNED_FORMAT_MAP = {
    'b': 'B',
    'h': 'H',
    'i': 'I',
    'l': 'L',
    'q': 'Q',
}
FORMAT_BIT_WIDTH = {
    'b': 8,
    'B': 8,
    'h': 16,
    'H': 16,
    'i': 32,
    'I': 32,
    'l': 32,
    'L': 32,
    'q': 64,
    'Q': 64,
}

_SKIP = object()
_BREAK = object()


@dataclass
class DecodedAttribute:
    name: str
    raw_bytes: bytes
    raw_value: Any
    value: Any
    meta: Dict[str, Any]
    next_cursor: int
    uses_absolute: bool


class AttrBlockDecoder:
    """Decode attribute blocks described by Raft device metadata."""

    _ARRAY_FORMAT_PATTERN = re.compile(r'([xcbB?hHiIlLqQnNefdspP])\[(\d+)\]')

    def decode_block(
        self,
        payload: bytes,
        attr_defs: Sequence[Dict[str, Any]],
        *,
        logger=None,
    ) -> List[DecodedAttribute]:
        cursor = 0
        results: List[DecodedAttribute] = []
        for attr in attr_defs:
            outcome = self._decode_single(payload, cursor, attr, logger)
            if outcome is _SKIP:
                continue
            if outcome is _BREAK:
                break
            results.append(outcome)
            cursor = outcome.next_cursor
        return results

    def _decode_single(self, payload, cursor, attr, logger):
        fmt = attr.get('t')
        if not fmt:
            return _SKIP

        normalized_fmt = self._normalize_format(fmt)
        # Wire layouts must never depend on native pointer size or alignment.
        if normalized_fmt[0] not in '<>!=':
            normalized_fmt = '=' + normalized_fmt

        try:
            size = struct.calcsize(normalized_fmt)
        except struct.error:
            if logger:
                logger.debug(f'Skip attr {attr.get("n")} invalid format: {fmt}')
            return _SKIP

        uses_absolute = 'at' in attr
        at_spec = attr.get('at')

        raw_bytes: Optional[bytes] = None

        if isinstance(at_spec, list):
            # Non-contiguous absolute positions; gather bytes explicitly
            if len(at_spec) != size or any(
                not isinstance(pos, int) or pos < 0 or pos >= len(payload) for pos in at_spec
            ):
                return _BREAK
            buffer = bytearray(size)
            for idx, pos in enumerate(at_spec):
                if idx >= size:
                    break
                try:
                    pos_int = int(pos)
                except (TypeError, ValueError):
                    continue
                if 0 <= pos_int < len(payload):
                    buffer[idx] = payload[pos_int]
            raw_bytes = bytes(buffer)
            read_offset = 0
        else:
            if at_spec is not None:
                try:
                    read_offset = int(at_spec)
                except (TypeError, ValueError):
                    if logger:
                        logger.debug(
                            f'Skip attr {attr.get("n")} invalid absolute offset: {at_spec}'
                        )
                    return _SKIP
            else:
                read_offset = cursor

            if read_offset < 0 or read_offset + size > len(payload):
                if uses_absolute:
                    if logger:
                        logger.debug(
                            f'Attr {attr.get("n")} absolute read outside payload: '
                            f'offset={read_offset} size={size} len={len(payload)}'
                        )
                    return _SKIP
                return _BREAK

            raw_bytes = payload[read_offset: read_offset + size]

        if raw_bytes is None or len(raw_bytes) != size:
            return _BREAK if not uses_absolute else _SKIP

        try:
            raw_tuple = struct.unpack(normalized_fmt, raw_bytes)
        except struct.error:
            if logger:
                logger.debug(
                    f'Struct unpack failed for attr {attr.get("n")} '
                    f'fmt={fmt} bytes={raw_bytes.hex()}'
                )
            return _SKIP

        mask_on_signed = attr.get('m') is not None and self._is_format_signed(normalized_fmt)
        ops_fmt = self._format_for_operations(normalized_fmt, mask_on_signed)

        try:
            ops_tuple = struct.unpack(ops_fmt, raw_bytes)
        except struct.error:
            # Fall back to previously unpacked tuple
            ops_tuple = raw_tuple

        values_for_ops = list(ops_tuple)
        item_width = self._infer_item_width(normalized_fmt)
        processed_values = self._apply_operations(values_for_ops, attr, mask_on_signed, item_width)

        raw_value = self._collapse_values(raw_tuple)
        processed_value = self._collapse_values(processed_values)

        next_cursor = cursor if uses_absolute else cursor + size

        name = attr.get('n') or f'field_{cursor}'
        return DecodedAttribute(
            name=name,
            raw_bytes=raw_bytes,
            raw_value=raw_value,
            value=processed_value,
            meta=attr,
            next_cursor=next_cursor,
            uses_absolute=uses_absolute,
        )

    def _apply_operations(self, values, attr, mask_on_signed, item_width):
        results = list(values)

        xor_value = self._parse_numeric(attr.get('x'))
        if xor_value is not None:
            xor_mask = int(xor_value)
            results = [(int(v) ^ xor_mask) if isinstance(v, int) else v for v in results]

        mask_value = self._parse_numeric(attr.get('m'))
        if mask_value is not None:
            mask_int = int(mask_value)
            if mask_on_signed:
                results = [
                    self._sign_extend(int(v), mask_int) if isinstance(v, int) else v
                    for v in results
                ]
            else:
                results = [(int(v) & mask_int) if isinstance(v, int) else v for v in results]

        sign_bit_pos = self._parse_numeric(attr.get('sb'))
        if sign_bit_pos is not None:
            sign_bit = 1 << int(sign_bit_pos)
            subtract_value = self._parse_numeric(attr.get('ss'))
            if subtract_value is not None:
                sub_int = int(subtract_value)
                results = [
                    (sub_int - int(v)) if isinstance(v, int) and (int(v) & sign_bit) else v
                    for v in results
                ]
            else:
                results = [
                    (int(v) - (sign_bit << 1)) if isinstance(v, int) and (int(v) & sign_bit) else v
                    for v in results
                ]

        bitshift = self._parse_numeric(attr.get('s'))
        if bitshift:
            shift_int = int(bitshift)
            if shift_int > 0:
                mask = (1 << item_width) - 1 if item_width else None
                results = (
                    [((int(v) & mask) >> shift_int) if isinstance(v, int) else v for v in results]
                    if mask is not None
                    else [(int(v) >> shift_int) if isinstance(v, int) else v for v in results]
                )
            elif shift_int < 0:
                shift_amount = -shift_int
                results = [(int(v) << shift_amount) if isinstance(v, int) else v for v in results]
                if item_width and self._is_format_signed(attr.get('t', '')):
                    # E.g. AMG8833's 12-bit signed pixel: <h, s=-4, d=64.
                    # Preserve the declared word width before engineering scaling.
                    word_mask = (1 << item_width) - 1
                    results = [
                        self._sign_extend(v, word_mask) if isinstance(v, int) else v
                        for v in results
                    ]

        divisor = self._parse_numeric(attr.get('d'))
        if divisor not in (None, 0):
            div_value = float(divisor)
            results = [
                (float(v) / div_value) if isinstance(v, (int, float)) else v for v in results
            ]

        add_value = self._parse_numeric(attr.get('a'))
        if add_value is not None:
            add_num = float(add_value)
            results = [(float(v) + add_num) if isinstance(v, (int, float)) else v for v in results]

        lut_entries = attr.get('lut')
        if isinstance(lut_entries, list) and lut_entries:
            transformed: List[Any] = []
            for v in results:
                if isinstance(v, (int, float)):
                    v_float = float(v)
                    if not math.isnan(v_float):
                        transformed.append(self._apply_lut(v_float, lut_entries))
                        continue
                transformed.append(v)
            results = transformed

        return results

    def _apply_lut(self, value: float, lut_entries: Iterable[Dict[str, Any]]):
        default_value: Optional[Any] = None
        for row in lut_entries:
            range_spec = row.get('r')
            if range_spec == '':
                default_value = row.get('v')
                continue
            if isinstance(range_spec, str) and self._value_in_range(value, range_spec):
                return row.get('v')
        return default_value if default_value is not None else value

    def _value_in_range(self, value: float, range_str: str) -> bool:
        rounded = int(round(value))
        for part in range_str.split(','):
            part = part.strip()
            if not part:
                continue
            if '-' in part:
                start_text, end_text = part.split('-', 1)
                start_val = self._parse_numeric(start_text)
                end_val = self._parse_numeric(end_text)
                if start_val is None or end_val is None:
                    continue
                start_int = int(start_val)
                end_int = int(end_val)
                if start_int <= rounded <= end_int:
                    return True
            else:
                target_val = self._parse_numeric(part)
                if target_val is None:
                    continue
                if rounded == int(target_val):
                    return True
        return False

    def _sign_extend(self, value: int, mask: int) -> int:
        value &= mask
        sign_bit_mask = (mask + 1) >> 1
        return value - (sign_bit_mask << 1) if value & sign_bit_mask else value

    def _format_for_operations(self, fmt: str, mask_on_signed: bool) -> str:
        if not mask_on_signed:
            return fmt
        chars = list(fmt)
        for idx, ch in enumerate(chars):
            if ch in UNSIGNED_FORMAT_MAP:
                chars[idx] = UNSIGNED_FORMAT_MAP[ch]
        return ''.join(chars)

    def _infer_item_width(self, fmt: str) -> Optional[int]:
        for ch in fmt:
            if ch in FORMAT_BIT_WIDTH:
                return FORMAT_BIT_WIDTH[ch]
        return None

    def _collapse_values(self, values: Iterable[Any]) -> Any:
        if not isinstance(values, (list, tuple)):
            return values
        seq = list(values)
        if not seq:
            return []
        if len(seq) == 1:
            return seq[0]
        return seq

    def _normalize_format(self, fmt: str) -> str:
        if '[' not in fmt:
            return fmt
        return self._ARRAY_FORMAT_PATTERN.sub(
            lambda match: f'{match.group(2)}{match.group(1)}',
            fmt,
        )

    def _parse_numeric(self, value: Any) -> Optional[float]:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            text = value.strip()
            if not text:
                return None
            try:
                if text.lower().startswith('0x'):
                    return float(int(text, 16))
                return float(int(text, 10))
            except ValueError:
                try:
                    return float(text)
                except ValueError:
                    return None
        return None

    def _is_format_signed(self, fmt: str) -> bool:
        for ch in fmt:
            if ch in SIGNED_FORMAT_CHARS:
                return True
        return False
