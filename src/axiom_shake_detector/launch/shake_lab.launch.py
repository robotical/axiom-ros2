"""Launch the teaching platform, which owns its independent ROS applications."""

from pathlib import Path

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    """Select input and local presentation settings."""
    defaults = {
        'with_driver': 'true',
        'transport': 'ws',
        'device_uri': 'ws://host.docker.internal:8765/ws',
        'serial_port': '/dev/ttyACM0',
        'imu_topic': '/axiom/bus_1/device_76a/imu/data_raw',
        'dashboard_host': '127.0.0.1',
        'dashboard_port': '8080',
        'recordings_dir': str(Path.home() / 'axiom-recordings'),
    }
    arguments = [DeclareLaunchArgument(k, default_value=v) for k, v in defaults.items()]
    params = {k: LaunchConfiguration(k) for k in defaults}
    params['dashboard_port'] = ParameterValue(
        LaunchConfiguration('dashboard_port'), value_type=int
    )
    params['with_driver'] = ParameterValue(LaunchConfiguration('with_driver'), value_type=bool)
    dashboard = Node(
        package='axiom_shake_detector',
        executable='teaching_dashboard',
        namespace='axiom',
        output='screen',
        parameters=[params],
    )
    return LaunchDescription(arguments + [dashboard])
