to connect axiom to wifi RICREST to w/TP-Link_092B/11630470/Marty_598c8a


to build everything:  colcon build --symlink-install
or specific package:
colcon build --symlink-install --packages-select <package_name>

to plot with plotjuggler:
ros2 run plotjuggler plotjuggler

clean build:
rm -rf build/ install/ log/

Connect ws:
ros2 launch axiom_driver axiom_minimal_launch.py \
  transport:=ws \
  device_uri:=ws://192.168.1.3/devjson \
  ws_path:=/ws ws_pcol:=RICSerial

Connect serial:
ros2 launch axiom_driver axiom_minimal_launch.py \
  transport:=serial \
  serial.port:=/dev/tty.usbmodem2101 serial.baud:=921600 serial.timeout:=0.02


Send Rest commands:
ros2 service call /ric_rest_url axiom_interfaces/srv/RicRestUrl \
  "{url_path: 'v', timeout: 3.0, ws_pcol: ''}"

to subscribe to published data:
ros2 service call /publish_data_subscription axiom_interfaces/srv/PublishedDataSubscription \
  "{'rate_hz': 10.0}"


To see raw IMU data:
<!-- no limit on the output -->
ros2 topic echo /LSM6DS_76a/imu/data_raw --full-length


create package with:
go to the src in root and:
ros2 pkg create --build-type ament_python <package_name> --dependencies rclpy