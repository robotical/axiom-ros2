# axiom_interfaces/msg/ThermalGrid.msg
std_msgs/Header header

# Width of the thermal grid in columns
uint32 width

# Height of the thermal grid in rows
uint32 height

# Temperature samples in Celsius, row-major order (length == width * height)
float32[] temperature_c
