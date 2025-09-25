import struct
from sensor_msgs.msg import Range
from .base import SensorDecoder

# Datasheet-ish defaults; adjust as needed for your module/mechanics
FOV_RAD = 0.47  # ~27 degrees
MIN_M = 0.02
MAX_M = 1.30

class VL53L4CDDecoder(SensorDecoder):
    topic_key = "VL53L4CD"

    def decode_samples(self, hex_payload: str):
        for i in range(0, len(hex_payload), 20):  # 10 bytes -> 20 hex chars
            chunk = hex_payload[i:i+20]
            if len(chunk) < 20:
                break
            b = bytes.fromhex(chunk)
            ts_wrapped = struct.unpack(">H", b[:2])[0]
            _ts_ms = self.unwrap_ts_ms(ts_wrapped)
            valid, dist_mm = struct.unpack(">BH", b[2:5])
            valid = (~valid) & 0x04  # from your code; treat 0x04 as valid bit
            if not valid:
                continue

            msg = Range()
            msg.header.frame_id = self.frame_id
            msg.radiation_type = Range.INFRARED
            msg.field_of_view = FOV_RAD
            msg.min_range = MIN_M
            msg.max_range = MAX_M
            msg.range = max(MIN_M, min(MAX_M, dist_mm / 1000.0))
            yield ("range/front", msg)