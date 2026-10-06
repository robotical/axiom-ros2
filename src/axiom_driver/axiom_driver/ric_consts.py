# Message type (2-bit) and protocol (6-bit) packed in one byte: (type<<6)|(protocol&0x3F)
TYPE_COMMAND = 0  # 0b00
TYPE_RESPONSE = 1  # 0b01
TYPE_PUBLISH = 2  # 0b10

# Protocol IDs
# 0 is used by firmware for ROSSerial-style devjson publishes on the console path
PROTO_ROSSERIAL = 0
PROTO_RICREST = 2
PROTO_BRIDGE_RICREST = 3

# RICREST element codes
ELEM_URL = 0x00
ELEM_CMDRESPJSON = 0x01
ELEM_BODY = 0x02
ELEM_COMMAND_FRAME = 0x03
ELEM_FILEBLOCK = 0x04

PROTO_RAWCMDFRAME = 0x3E


def pack_type_proto(msg_type: int, proto: int) -> int:
    return ((msg_type & 0x3) << 6) | (proto & 0x3F)
