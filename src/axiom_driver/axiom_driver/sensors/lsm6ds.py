import struct
from axiom_interfaces.msg import Imu6
from .base import SensorDecoder

DPS_TO_RAD = 0.017453292519943295
G_TO_MS2 = 9.80665

class LSM6DSDecoder(SensorDecoder):
    topic_key = "LSM6DS"

    def decode_samples(self, hex_payload: str):
        # each sample: 2B ts (big-endian), then 6x int16 little-endian (gx,gy,gz,ax,ay,az)
        for i in range(0, len(hex_payload), 28):
            chunk = hex_payload[i:i+28]
            if len(chunk) < 28:
                break
            b = bytes.fromhex(chunk)
            ts_wrapped = struct.unpack(">H", b[:2])[0]
            _ts_ms = self.unwrap_ts_ms(ts_wrapped)
            gx, gy, gz, ax, ay, az = struct.unpack("<hhhhhh", b[2:])

            msg = Imu6()
            msg.header.frame_id = self.frame_id
            # For now we leave header.stamp to the bridge, which can apply a device↔host offset

            # Scales mirrored from the current demo setup
            msg.gx = (gx / 16.384) * DPS_TO_RAD
            msg.gy = (gy / 16.384) * DPS_TO_RAD
            msg.gz = (gz / 16.384) * DPS_TO_RAD
            msg.ax = (ax / 8192.0) * G_TO_MS2
            msg.ay = (ay / 8192.0) * G_TO_MS2
            msg.az = (az / 8192.0) * G_TO_MS2

            yield ("imu/data_raw", msg)