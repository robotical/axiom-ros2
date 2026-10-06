from typing import Tuple


class RICFrame:
    """
    Pack and unpack the inner RIC frame.

    [msgNum:1][type/proto:1][elem:1][payload...]   No CRC here; framing comes from the outer layer
    (e.g., Mini-HDLC).
    """

    @staticmethod
    def pack(msgnum: int, type_proto: int, elem: int, payload: bytes) -> bytes:
        return bytes([msgnum & 0xFF, type_proto & 0xFF, elem & 0xFF]) + (payload or b'')

    @staticmethod
    def peek_header(buf: bytes) -> Tuple[int, int, int]:
        if len(buf) < 3:
            raise ValueError('RICFrame too short')
        return buf[0], buf[1], buf[2]
