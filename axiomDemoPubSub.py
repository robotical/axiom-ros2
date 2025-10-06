# Based on publisher_member_function.py demo by
# Copyright 2016 Open Source Robotics Foundation, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node

# from tutorial_interfaces.msg import Num

from std_msgs.msg import Int64

from std_msgs.msg import String, UInt16, Float32
from geometry_msgs.msg import Accel

import websocket
import rel
import struct
import json
from threading import Thread

class MinimalPublisher(Node):
    current_time_offset_ms = 0
    last_time_stamp_ms = 0

    publishers = {}

    def __init__(self):
        super().__init__('minimal_publisher')
        self.publisher_ = self.create_publisher(Int64, 'topic', 10)
        timer_period = 0.5  # seconds
        #self.timer = self.create_timer(timer_period, self.timer_callback)
        self.i = 0
        self.publisher2 = self.create_publisher(UInt16, 'axiom', 10)

    def timer_callback(self):
        msg = Int64()
        msg.data = self.i
        self.publisher_.publish(msg)
        self.get_logger().info('Publishing: "%d"' % msg.data)
        self.i += 1

    def chunk_string(self, string, length):
        return (string[0+i:length+i] for i in range(0, len(string), length))

    def publish(self, topic, msgtype, msg):
        if not topic in self.publishers:
            self.publishers[topic] = self.create_publisher(msgtype, topic, 10)
        self.publishers[topic].publish(msg)

    def decode_message(self, message):
        #msg = UInt16()
        #msg.data = 12
        #self.publisher2.publish(msg)
        # self.get_logger().info('Publishing: "%d' % msg.data)
        # Message is JSON
        message_dict = json.loads(message)
        # Iterate over buses and devices
        for bus in message_dict:
            #print(bus, " ", json.dumps(message_dict[bus]))
            for address in message_dict[bus]:
                topic = message_dict[bus][address]["_t"]
                topic_name = f'{topic}_{address}'
                #if bus == "I2CA":
                #    print(bus, " ", address, ": ", json.dumps(message_dict[bus][address]))
                    #for 
                # Get the hex message data (may contain multiple samples)

                #print("topic: ", topic)
                if topic == "LSM6DS":  
                    hex_data = message_dict[bus][address]["x"]
                    # Split based on message length
                    hex_samples_and_ts = self.chunk_string(hex_data, 28)
                    for hex_sample_and_ts in hex_samples_and_ts:
                        # Bytes from hex
                        bytes_sample_and_ts = bytes.fromhex(hex_sample_and_ts)
                        # Extract timestamp using struct
                        time_stamp_wrapped_ms = struct.unpack(">H", bytes_sample_and_ts[:2])[0]
                        # Unwrap the timestamp
                        if time_stamp_wrapped_ms < self.last_time_stamp_ms:
                            self.current_time_offset_ms += 65536
                        self.last_time_stamp_ms = time_stamp_wrapped_ms
                        time_stamp_ms = self.current_time_offset_ms + time_stamp_wrapped_ms
                        # Extract the samples using struct
                        gyro_x, gyro_y, gyro_z, acc_x, acc_y, acc_z = struct.unpack("<hhhhhh", bytes_sample_and_ts[2:])
                        # Form the decoded string
                        decoded_string = f"Gyro(dps): ({gyro_x/16.384:.2f}, {gyro_y/16.384:.2f}, {gyro_z/16.384:.2f}), Acc(g): ({acc_x/8192:.2f}, {acc_y/8192:.2f}, {acc_z/8192:.2f})"
                        #print(f"Time: {time_stamp_ms}, {decoded_string}")
                        msg = Accel()
                        msg.linear.x = acc_x/8192
                        msg.linear.y = acc_y/8192
                        msg.linear.z = acc_z/8192
                        msg.angular.x = gyro_x/16.384
                        msg.angular.y = gyro_y/16.384
                        msg.angular.z = gyro_z/16.384
                        self.publish(topic_name, Accel, msg)
                elif topic == "VL6180":
                    hex_data = message_dict[bus][address]["x"]
                    print(f"Hex data: {hex_data}")
                    # Split based on message length
                    hex_samples_and_ts = self.chunk_string(hex_data, 8)
                    for hex_sample_and_ts in hex_samples_and_ts:
                        # Bytes from hex
                        bytes_sample_and_ts = bytes.fromhex(hex_sample_and_ts)
                        print(f"hex sample %x, bytes sample: %x", hex_sample_and_ts, bytes_sample_and_ts)
                        # Extract timestamp using struct
                        time_stamp_wrapped_ms = struct.unpack(">H", bytes_sample_and_ts[:2])[0]
                        # Unwrap the timestamp
                        if time_stamp_wrapped_ms < self.last_time_stamp_ms:
                            self.current_time_offset_ms += 65536
                        self.last_time_stamp_ms = time_stamp_wrapped_ms
                        time_stamp_ms = self.current_time_offset_ms + time_stamp_wrapped_ms
                        # Extract the samples using struct
                        dist = struct.unpack("B", bytes_sample_and_ts[3:])[0]
                        # Form the decoded string
                        decoded_string = f"Dist (mm): {dist}"
                        print(f"Time: {time_stamp_ms}, {decoded_string}")
                elif topic == "VL53L4CD":
                    hex_data = message_dict[bus][address]["x"]
                    # self.get_logger().info('hex data: "%s"' % hex_data)
                    #print(f"Hex data: {hex_data}")
                    # Split based on message length
                    hex_samples_and_ts = self.chunk_string(hex_data, 10)
                    for hex_sample_and_ts in hex_samples_and_ts:
                        # Bytes from hex
                        bytes_sample_and_ts = bytes.fromhex(hex_sample_and_ts)
                        #print(f"hex sample %x, bytes sample: %x", hex_sample_and_ts, bytes_sample_and_ts)
                        # Extract timestamp using struct
                        time_stamp_wrapped_ms = struct.unpack(">H", bytes_sample_and_ts[:2])[0]
                        # Unwrap the timestamp
                        if time_stamp_wrapped_ms < self.last_time_stamp_ms:
                            self.current_time_offset_ms += 65536
                        self.last_time_stamp_ms = time_stamp_wrapped_ms
                        time_stamp_ms = self.current_time_offset_ms + time_stamp_wrapped_ms
                        # Extract the samples using struct
                        valid, dist = struct.unpack(">BH", bytes_sample_and_ts[2:])
                        valid = (~valid) & 0x04
                        # Form the decoded string
                        decoded_string = f"Dist (mm): {dist} valid {valid}"
                        print(f"Time: {time_stamp_ms}, {decoded_string}")
                        msg = UInt16()
                        msg.data = dist
                        #self.publisher2.publish(msg)
                        if valid:
                            self.publish(topic_name, UInt16, msg)
                        # self.get_logger().info('Publishing: "%d"' % msg.data)
                elif topic == "AHT20":
                    hex_data = message_dict[bus][address]["x"]
                    #print(f"Hex data: {hex_data}")
                    # Split based on message length
                    hex_samples_and_ts = self.chunk_string(hex_data, 16)
                    for hex_sample_and_ts in hex_samples_and_ts:
                        # Bytes from hex
                        bytes_sample_and_ts = bytes.fromhex(hex_sample_and_ts)
                        #print("hex sample: ", hex_sample_and_ts, " bytes sample: ", bytes_sample_and_ts)
                        #print("bytes length %d" % len(bytes_sample_and_ts))
                        # Extract timestamp using struct
                        time_stamp_wrapped_ms = struct.unpack(">H", bytes_sample_and_ts[:2])[0]
                        # Unwrap the timestamp
                        if time_stamp_wrapped_ms < self.last_time_stamp_ms:
                            self.current_time_offset_ms += 65536
                        self.last_time_stamp_ms = time_stamp_wrapped_ms
                        time_stamp_ms = self.current_time_offset_ms + time_stamp_wrapped_ms
                        # Extract the samples using struct
                        humid = struct.unpack(">Ic", bytes_sample_and_ts[3:])[0]
                        temp = struct.unpack(">I", bytes_sample_and_ts[4:])[0]
                        humid = ((humid & 0xfffff000) >> 12) / 10485.76
                        temp = ((temp & 0x000fffff) / 5242.88) - 50
                        # Form the decoded string
                        decoded_string = f"humid: {humid} temp {temp}"
                        print(f"Time: {time_stamp_ms}, {decoded_string}")
                        msg = Float32()
                        msg.data = humid
                        #self.publisher2.publish(msg)
                        self.publish(f'{topic_name}_humidity', Float32, msg)
                        msg.data = temp
                        self.publish(f'{topic_name}_temp', Float32, msg)
                        #self.get_logger().info('Publishing: "%d"' % msg.data)
                    
        
    def on_message(self, ws, message):
        #print("Received message ", json.dumps(message))
        self.decode_message(message)

    def on_error(self, ws, error):
        print(error)

    def on_close(self, ws, close_status_code, close_msg):
        print("### closed ###")

    def on_open(self, ws):
        # Subscribe to messages
        subscribe_topic = "devjson"
        subscribe_cmd = {
            "cmdName": "subscription",
            "action": "update",
            "pubRecs": [
                {"name": subscribe_topic, "trigger": "timeorchange", "rateHz": 0.1},
            ]
        }
        print("Opened connection - subscribing to messages with ", json.dumps(subscribe_cmd))
        ws.send(json.dumps(subscribe_cmd))


def main(args=None):
    try:
        with rclpy.init(args=args):
            minimal_publisher = MinimalPublisher()

            DEVICE_IP_ADDRESS = "192.168.1.3"
            #DEVICE_IP_ADDRESS = "192.168.8.120"
            ws = websocket.WebSocketApp("ws://" + DEVICE_IP_ADDRESS + "/devjson",
                on_open=minimal_publisher.on_open, on_message=minimal_publisher.on_message, on_error=minimal_publisher.on_error, on_close=minimal_publisher.on_close)
            #ws.run_forever(dispatcher=rel, reconnect=5)
            #rel.signal(2, rel.abort)
            #rel.dispatch()

            Thread(target=ws.run_forever).start()

            rclpy.spin(minimal_publisher)

            
    except (KeyboardInterrupt, ExternalShutdownException):
        pass


if __name__ == '__main__':
    main()
