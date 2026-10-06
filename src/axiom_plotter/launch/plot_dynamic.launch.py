from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription(
        [
            Node(
                package='axiom_plotter',
                executable='dynamic_grapher',
                name='axiom_dynamic_plotter',
                output='screen',
                arguments=[
                    '--topic-regex',
                    '/axiom/',
                    '--history-sec',
                    '120',
                    '--rate-hz',
                    '15',
                    '--sensor-qos',
                ],
            ),
        ]
    )
