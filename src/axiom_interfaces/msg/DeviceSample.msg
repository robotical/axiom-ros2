# One decoded measurement, including vectors such as a thermal grid.
std_msgs/Header header
string bus
string address
string device_type
string group
# Standards-compliant JSON: invalid numeric values are null, with valid=false.
string values_json
float64 device_time_us
float64 poll_time_us
builtin_interfaces/Time received_at
string time_quality
uint32 overflow
