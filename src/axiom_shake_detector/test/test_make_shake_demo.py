"""Synthetic MCAP examples use the current public IMU topic and keep CLI overrides."""

from pathlib import Path
import subprocess
import sys

import pytest

pytest.importorskip('rclpy')
from rclpy.serialization import deserialize_message  # noqa: E402
import rosbag2_py  # noqa: E402
from sensor_msgs.msg import Imu  # noqa: E402


@pytest.mark.parametrize('override', [None, '/lesson/custom_imu'])
def test_make_shake_demo_writes_actual_mcap_on_current_topic(tmp_path, override):
    script = Path(__file__).resolve().parents[3] / 'scripts' / 'make_shake_demo.py'
    destination = tmp_path / 'demo'
    command = [sys.executable, str(script), str(destination)]
    if override:
        command.extend(['--topic', override])
    result = subprocess.run(command, check=True, text=True, capture_output=True, timeout=10)
    assert '600 IMU samples' in result.stdout
    topic = override or '/axiom/lsm6ds_b1_76a/data_raw'
    reader = rosbag2_py.SequentialReader()
    reader.open(rosbag2_py.StorageOptions(uri=str(destination), storage_id='mcap'),
                rosbag2_py.ConverterOptions('', ''))
    metadata = reader.get_all_topics_and_types()
    assert [(row.name, row.type) for row in metadata] == [(topic, 'sensor_msgs/msg/Imu')]
    samples = []
    while reader.has_next():
        name, data, stamp = reader.read_next()
        assert name == topic and '/bus_' not in name
        message = deserialize_message(data, Imu)
        assert message.header.frame_id == 'synthetic_imu'
        assert message.linear_acceleration.z == pytest.approx(9.81)
        assert message.orientation_covariance[0] == -1.0
        assert stamp == message.header.stamp.sec * 1_000_000_000 + message.header.stamp.nanosec
        samples.append(stamp)
    assert len(samples) == 600
    assert samples[-1] - samples[0] == 5_990_000_000
