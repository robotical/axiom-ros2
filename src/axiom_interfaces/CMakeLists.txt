cmake_minimum_required(VERSION 3.20)
project(axiom_interfaces)

if(CMAKE_COMPILER_IS_GNUCXX OR CMAKE_CXX_COMPILER_ID MATCHES "Clang")
  add_compile_options(-Wall -Wextra -Wpedantic)
endif()

find_package(ament_cmake REQUIRED)
find_package(rosidl_default_generators REQUIRED)
find_package(std_msgs REQUIRED) 

set(msg_files
  "msg/Imu6.msg"
  "msg/AxiomPowerState.msg"
  "msg/VL53L4CDReading.msg"
  "msg/ThermalGrid.msg"
)

set(srv_files
  "srv/Connect.srv"
  "srv/Disconnect.srv"
  "srv/GetConnectionState.srv"
  "srv/Ping.srv"
  "srv/PublishedDataSubscription.srv"
  "srv/RicRestUrl.srv"
)

rosidl_generate_interfaces(${PROJECT_NAME}
  ${msg_files}
  ${srv_files}
  DEPENDENCIES std_msgs          
)

ament_export_dependencies(rosidl_default_runtime std_msgs)  
ament_package()
