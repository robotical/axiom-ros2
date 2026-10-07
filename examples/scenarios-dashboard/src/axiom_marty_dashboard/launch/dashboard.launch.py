"""Start the optional observer alongside an already running ROS graph."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import EnvironmentVariable, LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("host", default_value="127.0.0.1"),
            DeclareLaunchArgument("port", default_value=EnvironmentVariable(
                "AXIOM_DASHBOARD_PORT", default_value="8083")),
            Node(
                package="axiom_marty_dashboard",
                executable="dashboard",
                output="screen",
                parameters=[
                    {
                        "host": LaunchConfiguration("host"),
                        "port": ParameterValue(LaunchConfiguration("port"), value_type=int),
                    }
                ],
            ),
        ]
    )
