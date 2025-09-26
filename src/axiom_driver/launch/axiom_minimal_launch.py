from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        # Core
        DeclareLaunchArgument('transport', default_value='ws'),
        DeclareLaunchArgument('device_uri', default_value='ws://192.168.1.7/devjson'),
        DeclareLaunchArgument('auto_connect', default_value='true'),
        DeclareLaunchArgument('frame_id', default_value='axiom_link'),
        DeclareLaunchArgument('namespace', default_value=''),  # optional namespace

        # Serial
        DeclareLaunchArgument('serial.port', default_value='/dev/cu.usbmodem2101'),
        DeclareLaunchArgument('serial.baud', default_value='115200'),
        DeclareLaunchArgument('serial.timeout', default_value='0.02'),
        DeclareLaunchArgument('serial.mode', default_value='auto'),
        DeclareLaunchArgument('serial.autosub', default_value='true'),
        DeclareLaunchArgument('serial.devjson_rate_hz', default_value='0.1'),

        Node(
            package='axiom_driver',
            executable='axiom_bridge_node',
            name='axiom_bridge_node',
            namespace=LaunchConfiguration('namespace'),
            parameters=[{
                'transport': LaunchConfiguration('transport'),
                'device_uri': LaunchConfiguration('device_uri'),
                'auto_connect': LaunchConfiguration('auto_connect'),
                'frame_id': LaunchConfiguration('frame_id'),
                'serial.port': LaunchConfiguration('serial.port'),
                'serial.baud': LaunchConfiguration('serial.baud'),
                'serial.timeout': LaunchConfiguration('serial.timeout'),
                'serial.mode': LaunchConfiguration('serial.mode'),
                'serial.autosub': LaunchConfiguration('serial.autosub'),
                'serial.devjson_rate_hz': LaunchConfiguration('serial.devjson_rate_hz'),
            }],
            arguments=['--ros-args', '--log-level', 'INFO'],
        ),
    ])