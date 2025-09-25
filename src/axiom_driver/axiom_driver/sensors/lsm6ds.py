import struct
from sensor_msgs.msg import Imu
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
            ts_ms = self.unwrap_ts_ms(ts_wrapped)
            gx, gy, gz, ax, ay, az = struct.unpack("<hhhhhh", b[2:])

            msg = Imu()
            msg.header.frame_id = self.frame_id
            # Put host time for now; optionally convert ts_ms to ROS time with an offset
            # msg.header.stamp = ... (bridge can fill common stamp)

            # scales from your demo
            msg.angular_velocity.x = (gx / 16.384) * DPS_TO_RAD
            msg.angular_velocity.y = (gy / 16.384) * DPS_TO_RAD
            msg.angular_velocity.z = (gz / 16.384) * DPS_TO_RAD
            msg.linear_acceleration.x = (ax / 8192.0) * G_TO_MS2
            msg.linear_acceleration.y = (ay / 8192.0) * G_TO_MS2
            msg.linear_acceleration.z = (az / 8192.0) * G_TO_MS2

            # unknown covariances
            msg.angular_velocity_covariance[0] = -1.0
            msg.linear_acceleration_covariance[0] = -1.0

            yield ("imu/data_raw", msg)