"""Validate the public bringup arguments without connecting to hardware."""

import importlib.util
from pathlib import Path

from axiom_driver.config import DEFAULT_PARAMETERS
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription


def test_bringup_exposes_driver_parameters_and_optional_tools():
    path = Path(__file__).parents[1] / 'launch' / 'bringup.launch.py'
    spec = importlib.util.spec_from_file_location('bringup_launch', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    entities = module.generate_launch_description().entities
    arguments = {item.name for item in entities if isinstance(item, DeclareLaunchArgument)}
    assert set(DEFAULT_PARAMETERS) <= arguments
    assert {'namespace', 'params_file', 'boards_file', 'enable_plotter', 'enable_thermal'} <= arguments
    assert sum(isinstance(item, IncludeLaunchDescription) for item in entities) == 1


def test_installed_driver_launch_accepts_json_and_exits_cleanly(tmp_path):
    import os
    import signal
    import subprocess
    import time

    log_path = tmp_path / 'launch.log'
    command = [
        'ros2',
        'launch',
        'axiom_driver',
        'axiom_minimal_launch.py',
        'auto_connect:=false',
        'namespace:=alignment_launch',
        'sensor_frames:={"1:6a":"imu_link"}',
        'sensor_qos.overrides:={"bus_1/device_29/range":{"depth":3}}',
    ]
    with log_path.open('w') as log:
        process = subprocess.Popen(command, stdout=log, stderr=log, start_new_session=True)
        try:
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if 'One upstream acquisition stream' in log_path.read_text():
                    break
                assert process.poll() is None, log_path.read_text()
                time.sleep(0.05)
            else:
                raise AssertionError(log_path.read_text())
            process.send_signal(signal.SIGINT)
            assert process.wait(timeout=8) == 0, log_path.read_text()
        finally:
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait()
    assert 'Traceback' not in log_path.read_text()
