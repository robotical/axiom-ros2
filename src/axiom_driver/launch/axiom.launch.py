"""Automatic USB and Wi-Fi discovery with optional board configuration."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('boards_file', default_value=EnvironmentVariable(
            'AXIOM_ROS_BOARDS_FILE', default_value='')),
        Node(
            package='axiom_driver', executable='axiom_discovery', output='screen',
            parameters=[{'boards_file': ParameterValue(
                LaunchConfiguration('boards_file'), value_type=str)}],
        ),
    ])
