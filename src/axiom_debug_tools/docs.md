Use `/axiom/devices` to discover actual topic prefixes. For example:

```bash
ros2 topic echo /axiom/bus_1/device_76a/imu/data_raw --qos-reliability best_effort
```

The six-axis IMU message contains acceleration and angular velocity, with no
orientation estimate. Magnetometer and IMU temperature topics are not fabricated.
