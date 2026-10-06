"""
Bounded native decoders for the current firmware's custom response records.

Metadata is data, never executable Python/JavaScript. Unknown custom records fail explicitly so raw
capture/diagnostics can preserve them without inventing values.
"""

from dataclasses import dataclass
import hashlib
import json
import struct

from .custom_contracts import SUPPORTED_CUSTOM_SHA256


class DecodeError(ValueError):
    """A record is malformed or its decoding contract is unsupported."""


@dataclass
class CustomResult:
    rows: list
    engineering: bool = False
    overflow: int = 0


def crc8(data):
    """Sensirion CRC-8, polynomial 0x31, initial value 0xff."""
    crc = 0xFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ (0x31 if crc & 0x80 else 0)) & 0xFF
    return crc


def decode_custom(payload, metadata):
    definition = metadata.get('c', {})
    name = definition.get('n')
    if name not in SUPPORTED_CUSTOM_SHA256:
        raise DecodeError(f'Unsupported custom decoder: {name!r}')
    signature = json.dumps(
        {k: ''.join(v.split()) if isinstance(v, str) else v for k, v in definition.items()},
        sort_keys=True,
    )
    if hashlib.sha256(signature.encode()).hexdigest() != SUPPORTED_CUSTOM_SHA256[name]:
        raise DecodeError(f'Custom decoder contract changed: {name}; update decoder and fixtures')
    rows = []
    overflow = 0
    if name == 'lsm6ds_fifo':
        if len(payload) < 4:
            raise DecodeError('LSM6DS FIFO header truncated')
        words = int.from_bytes(payload[:2], 'little') & 0x0FFF
        pattern = int.from_bytes(payload[2:4], 'little') & 0x03FF
        skip = (6 - pattern % 6) % 6
        count = min(max(0, (words - skip) // 6), (240 - skip * 2) // 12)
        start = 4 + skip * 2
        if count and start + count * 12 > len(payload):
            raise DecodeError('LSM6DS FIFO sample truncated')
        for i in range(count):
            values = struct.unpack_from('<6h', payload, start + i * 12)
            rows.append(dict(zip(('gx', 'gy', 'gz', 'ax', 'ay', 'az'), values)))
        overflow = int(bool(payload[1] & 0x40))
    elif name == 'vcp_fifo':
        if len(payload) < 4:
            raise DecodeError('VCP FIFO header truncated')
        count, mode, channel, overflow = payload[:4]
        if mode not in (1, 2) or channel > 3:
            raise DecodeError('Unsupported VCP FIFO mode/channel')
        width = 8 if mode == 1 else 2
        if count > 128 // width or 4 + count * width > len(payload):
            raise DecodeError('VCP FIFO sample count exceeds block')
        for i in range(count):
            values = [0, 0, 0, 0]
            if mode == 1:
                values = struct.unpack_from('>4h', payload, 4 + i * width)
            else:
                values[channel] = struct.unpack_from('>h', payload, 4 + i * width)[0]
            rows.append(dict(zip(('V1', 'V2', 'V3', 'I'), values), ovf=overflow))
    elif name == 'max30101_fifo':
        if len(payload) < 3:
            raise DecodeError('MAX30101 FIFO header truncated')
        count = (payload[0] + 32 - payload[2]) % 32
        # The fixed poll reads at most eight FIFO pairs. Further pairs remain
        # in the device FIFO; the register count can legitimately exceed eight.
        count = min(count, (len(payload) - 3) // 6)
        overflow = payload[1] & 0x1F
        for i in range(count):
            start = 3 + i * 6
            rows.append(
                {
                    'Red': int.from_bytes(payload[start: start + 3], 'big'),
                    'IR': int.from_bytes(payload[start + 3: start + 6], 'big'),
                }
            )
    elif name == 'gravity_o2_calc':
        if len(payload) != 3:
            raise DecodeError('GravityO2 requires three bytes')
        rows = [{'oxygen': (20.9 / 120) * (payload[0] + payload[1] / 10 + payload[2] / 100)}]
        return CustomResult(rows, engineering=True)
    elif name == 'ltr329_light_calc':
        if len(payload) != 4:
            raise DecodeError('LTR-329 requires four bytes')
        ir, combined = struct.unpack('<HH', payload)
        return CustomResult([{'ir': ir, 'visible': combined - ir}], engineering=True)
    elif name == 'scd40_calc':
        if len(payload) != 9:
            raise DecodeError('SCD40 requires three words with CRC')
        words = []
        for start in (0, 3, 6):
            data = payload[start: start + 2]
            if crc8(data) != payload[start + 2]:
                raise DecodeError('SCD40 measurement CRC mismatch')
            words.append(int.from_bytes(data, 'big'))
        # The catalogue's scd40_calc pseudocode treats bytes as words and
        # duplicates scaling. Use Sensirion's specified wire conversion once:
        # https://sensirion.github.io/python-i2c-scd4x/api.html
        return CustomResult(
            [
                {
                    'CO2': words[0],
                    'temperature': -45 + 175 * words[1] / 65535,
                    'humidity': 100 * words[2] / 65535,
                }
            ],
            engineering=True,
        )
    else:
        raise DecodeError(f'Unsupported custom decoder: {name!r}')
    expected = {attr['n'] for attr in metadata['a']}
    if any(set(row) != expected for row in rows):
        raise DecodeError(f'Custom decoder schema changed: {name}')
    return CustomResult(rows, overflow=overflow)
