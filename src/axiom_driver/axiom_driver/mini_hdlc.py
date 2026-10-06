FLAG_DEFAULT = 0xE7
ESC_DEFAULT = 0xD7
XOR_DEFAULT = 0x20

# CRC-16-CCITT (poly 0x1021, init 0xFFFF), big-endian transmit
_CRC_TAB = [0] * 256
for i in range(256):
    crc = i << 8
    for _ in range(8):
        crc = ((crc << 1) ^ 0x1021) & 0xFFFF if (crc & 0x8000) else (crc << 1) & 0xFFFF
    _CRC_TAB[i] = crc


def crc16_ccitt(data: bytes, init: int = 0xFFFF) -> int:
    crc = init
    for b in data:
        crc = _CRC_TAB[((crc >> 8) ^ b) & 0xFF] ^ ((crc << 8) & 0xFFFF)
    return crc & 0xFFFF


class MiniHDLC:
    def __init__(self, flag: int = FLAG_DEFAULT, esc: int = ESC_DEFAULT, xo: int = XOR_DEFAULT):
        """
        Minimal HDLC-like framing used by firmware.

        Defaults match Axiom firmware: flag=0xE7, esc=0xD7, xor=0x20.
        """
        self.flag = flag
        self.esc = esc
        self.xo = xo

    def encode(self, payload: bytes) -> bytes:
        crc = crc16_ccitt(payload)
        out = bytearray([self.flag])
        for b in payload + bytes([(crc >> 8) & 0xFF, crc & 0xFF]):
            if b in (self.flag, self.esc):
                out.append(self.esc)
                out.append(b ^ self.xo)
            else:
                out.append(b)
        out.append(self.flag)
        return bytes(out)

    def try_decode(self, framed: bytes):
        """
        Return (ok, payload) if a single full frame is present; else (False, b'').

        This simple decoder expects exactly one frame: flag ... flag.
        """
        if len(framed) < 4:  # min flag, 2 crc, flag
            return False, b''
        if framed[0] != self.flag or framed[-1] != self.flag:
            return False, b''
        data = bytearray()
        i = 1
        while i < len(framed) - 1:
            b = framed[i]
            if b == self.esc:
                i += 1
                if i >= len(framed) - 1:
                    return False, b''
                data.append(framed[i] ^ self.xo)
            else:
                data.append(b)
            i += 1
        if len(data) < 2:
            return False, b''
        recv_crc = (data[-2] << 8) | data[-1]
        payload = bytes(data[:-2])
        calc_crc = crc16_ccitt(payload)
        if recv_crc != calc_crc:
            return False, b''
        return True, payload
