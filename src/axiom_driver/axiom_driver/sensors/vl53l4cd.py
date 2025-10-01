import struct
from sensor_msgs.msg import Range
from .base import SensorDecoder
import rclpy.logging
logger = rclpy.logging.get_logger("VL53L4CDDecoder")
from rclpy.clock import Clock  # <-- add this import

# Approximate defaults; adjust if the module/mechanics differ
FOV_RAD = 0.47  # ~27 degrees
MIN_M = 0.02
MAX_M = 1.30

class VL53L4CDDecoder(SensorDecoder):
    topic_key = "VL53L4CD"

    def decode_samples(self, hex_payload: str):
        for hex_sample_and_ts in self.chunk_string(hex_payload, 10):
            if len(hex_sample_and_ts) < 10:
                logger.warn(f"Short chunk ({len(hex_sample_and_ts)}): {hex_sample_and_ts}")
                continue

            b = bytes.fromhex(hex_sample_and_ts)
            ts_wrapped = struct.unpack(">H", b[:2])[0]
            _ts_ms = self.unwrap_ts_ms(ts_wrapped)

            valid_raw, dist_mm = struct.unpack(">BH", b[2:5])

            valid = (valid_raw & 0x04) != 0

            logger.info(
                f"VL53L4CD raw=0x{hex_sample_and_ts} ts={_ts_ms} valid_raw=0x{valid_raw:02X} "
                f"bit2={(valid_raw & 0x04)!=0} dist_mm={dist_mm}"
            )

            # Treat zero as no-return; keep if you want strictness
            if not valid or dist_mm == 0:
                logger.warn(f"Invalid measurement: {hex_sample_and_ts}")
                continue

            msg = Range()
            msg.header.frame_id = self.frame_id
            msg.header.stamp = Clock().now().to_msg()
            msg.radiation_type = Range.INFRARED
            msg.field_of_view = FOV_RAD
            msg.min_range = MIN_M
            msg.max_range = MAX_M
            msg.range = max(MIN_M, min(MAX_M, dist_mm / 1000.0))

            yield ("range/front", msg)
    def chunk_string(self, string, length):
        return (string[0+i:length+i] for i in range(0, len(string), length))