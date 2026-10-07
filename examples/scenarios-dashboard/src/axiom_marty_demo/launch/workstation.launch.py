"""Optional guide only. Drivers, acquisition and RViz remain console steps."""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            DeclareLaunchArgument("with_dashboard", default_value="false"),
            Node(
                package="axiom_marty_dashboard",
                executable="dashboard",
                condition=IfCondition(LaunchConfiguration("with_dashboard")),
                output="screen",
            ),
        ]
    )
