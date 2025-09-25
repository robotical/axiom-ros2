import struct
from sensor_msgs.msg import Temperature, RelativeHumidity
from .base import SensorDecoder

class AHT20Decoder(SensorDecoder):
    topic_key = "AHT20"

    def decode_samples(self, hex_payload: str):
        for i in range(0, len(hex_payload), 32):  # 16 bytes -> 32 hex chars
            chunk = hex_payload[i:i+32]
            if len(chunk) < 32:
                break
            b = bytes.fromhex(chunk)
            ts_wrapped = struct.unpack(">H", b[:2])[0]
            _ts_ms = self.unwrap_ts_ms(ts_wrapped)

            # Bit slicing follows the device data layout
            humid_raw = struct.unpack(">I", b[3:7])[0]
            temp_raw  = struct.unpack(">I", b[4:8])[0]
            humid = ((humid_raw & 0xFFFFF000) >> 12) / 10485.76
            temp_c = ((temp_raw  & 0x000FFFFF) / 5242.88) - 50.0

            t = Temperature()
            t.header.frame_id = self.frame_id
            t.temperature = float(temp_c)
            t.variance = 0.0
            yield ("environment/temperature", t)

            h = RelativeHumidity()
            h.header.frame_id = self.frame_id
            h.relative_humidity = max(0.0, min(1.0, humid / 100.0))
            h.variance = 0.0
            yield ("environment/humidity", h)