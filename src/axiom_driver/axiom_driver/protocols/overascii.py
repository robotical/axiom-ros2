# axiom_driver/protocols/overascii.py
from typing import Callable, Optional

# Constants from the firmware specification
OA_E1, OA_E2, OA_E3, OA_XOR = 0x85, 0x8E, 0x8F, 0x20


def encode(data: bytes) -> bytes:
    """
    Encode bytes into the firmware OverAscii stream.

    Rules:
      0x00-0x0F  ->  0x85, (b ^ 0x20) | 0x80
      0x10-0x7F  ->  b | 0x80
      0x80-0x8F  ->  0x8E, (b ^ 0x20)
      0x90-0xFF  ->  0x8F, b
    """
    out = bytearray()
    for b in data:
        if b <= 0x0F:
            out += bytes([OA_E1, (b ^ OA_XOR) | 0x80])
        elif 0x10 <= b <= 0x7F:
            out += bytes([b | 0x80])
        elif 0x80 <= b <= 0x8F:
            out += bytes([OA_E2, (b ^ OA_XOR)])
        else:
            out += bytes([OA_E3, b])
    return bytes(out)


class Decoder:
    """
    Streaming ProtocolOverAscii decoder.

    Feed console bytes; it emits the recovered binary stream via on_binary(cb).
    """

    def __init__(self):
        self._state = 'IDLE'
        # Callback set by owner; receives recovered binary chunks
        self.on_binary: Optional[Callable[[bytes], None]] = None

    def feed(self, chunk: bytes):
        if not chunk:
            return
        emit = self.on_binary
        for b in chunk:
            if self._state == 'IDLE':
                if b == OA_E1:
                    self._state = 'E1'
                elif b == OA_E2:
                    self._state = 'E2'
                elif b == OA_E3:
                    self._state = 'E3'
                elif b & 0x80:  # high bit set -> 0x10-0x7F encoded
                    out = bytes([b & 0x7F])  # clear MSB
                    if emit:
                        emit(out)
                else:
                    # The console path handles plain ASCII separately.
                    continue
            elif self._state == 'E1':  # 0x00-0x0F form
                self._state = 'IDLE'
                out = bytes([(b & 0x7F) ^ OA_XOR])
                if emit:
                    emit(out)
            elif self._state == 'E2':  # 0x80-0x8F form
                self._state = 'IDLE'
                out = bytes([(b ^ OA_XOR)])
                if emit:
                    emit(out)
            elif self._state == 'E3':  # 0x90-0xFF form
                self._state = 'IDLE'
                if emit:
                    emit(bytes([b]))
