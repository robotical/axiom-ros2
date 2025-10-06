# axiom_interfaces/msg/VL53L4CDReading.msg
std_msgs/Header header

# Whether the measurement is valid (device-side flag)
bool valid

# Distance in meters (SI)
float32 distance_m

# Raw distance in millimeters (as reported by device, if available)
uint32 distance_mm
