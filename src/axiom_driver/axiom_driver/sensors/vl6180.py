import struct
from sensor_msgs.msg import Range
from .base import SensorDecoder

FOV_RAD = 0.47
MIN_M = 0.01
MAX_M = 0.20

class VL6180Decoder(SensorDecoder):
    topic_key = "VL6180"

    def decode_samples(self, hex_payload: str):
        for i in range(0, len(hex_payload), 16):  # 8 bytes -> 16 hex chars
            chunk = hex_payload[i:i+16]
            if len(chunk) < 16:
                break
            b = bytes.fromhex(chunk)
            ts_wrapped = struct.unpack(">H", b[:2])[0]
            _ts_ms = self.unwrap_ts_ms(ts_wrapped)
            # bytes[2] may carry a status; we follow the current convention and use byte[3]
            dist_mm = struct.unpack("B", b[3:4])[0]

            msg = Range()
            msg.header.frame_id = self.frame_id
            msg.radiation_type = Range.INFRARED
            msg.field_of_view = FOV_RAD
            msg.min_range = MIN_M
            msg.max_range = MAX_M
            msg.range = max(MIN_M, min(MAX_M, dist_mm / 1000.0))
            yield ("range/short", msg)