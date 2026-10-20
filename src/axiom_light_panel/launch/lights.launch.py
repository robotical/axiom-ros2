"""Open RViz lighting controls alongside an independently running Axiom driver."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    """Discover live lights without specifying board namespaces or addresses."""
    config = Path(get_package_share_directory('axiom_light_panel')) / 'config' / 'lights.rviz'
    return LaunchDescription([Node(package='rviz2', executable='rviz2',
                                   arguments=['-d', str(config)], output='screen')])
