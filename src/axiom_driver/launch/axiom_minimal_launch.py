from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    
    return LaunchDescription([
        DeclareLaunchArgument('device_uri', default_value='ws://192.168.1.7/devjson'),
        DeclareLaunchArgument('auto_connect', default_value='true'),
        DeclareLaunchArgument('frame_id', default_value='axiom_link'),
        DeclareLaunchArgument('namespace', default_value=''),  # optional

        Node(
            package='axiom_driver',
            executable='axiom_bridge_node',
            name='axiom_bridge_node',
            namespace=LaunchConfiguration('namespace'),  
            parameters=[{
                'device_uri': LaunchConfiguration('device_uri'),
                'auto_connect': LaunchConfiguration('auto_connect'),
                'frame_id': LaunchConfiguration('frame_id'),
            }],
            arguments=['--ros-args', '--log-level', 'INFO'],
        )
    ])