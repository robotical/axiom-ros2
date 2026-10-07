"""Board driver with optional visualization, all scoped to one namespace."""

from axiom_driver.config import DEFAULT_PARAMETERS
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import EnvironmentVariable, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    arguments = [
        DeclareLaunchArgument('namespace', default_value='axiom'),
        DeclareLaunchArgument('boards_file', default_value=EnvironmentVariable(
            'AXIOM_ROS_BOARDS_FILE', default_value='')),
        DeclareLaunchArgument(
            'params_file',
            default_value=PathJoinSubstitution(
                [FindPackageShare('axiom_driver'), 'config', 'axiom.yaml']
            ),
        ),
    ]
    for name in DEFAULT_PARAMETERS:
        arguments.append(
            DeclareLaunchArgument(name, default_value='')
        )
    arguments += [
        DeclareLaunchArgument('enable_plotter', default_value='false'),
        DeclareLaunchArgument('plotter.topic_regex', default_value='/imu/data_raw$'),
        DeclareLaunchArgument('plotter.field', default_value='linear_acceleration.z'),
        DeclareLaunchArgument('enable_thermal', default_value='false'),
        DeclareLaunchArgument(
            'thermal.input_topic', default_value='bus_1/device_169/thermal/grid'
        ),
        DeclareLaunchArgument('enable_rqt', default_value='false'),
    ]
    driver = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution(
                [FindPackageShare('axiom_driver'), 'launch', 'axiom_minimal_launch.py']
            )
        ),
        launch_arguments={
            name: LaunchConfiguration(name)
            for name in ['namespace', 'params_file', 'boards_file'] + list(DEFAULT_PARAMETERS)
        }.items(),
    )
    plotter = Node(
        package='axiom_plotter',
        executable='dynamic_grapher',
        namespace=LaunchConfiguration('namespace'),
        output='screen',
        condition=IfCondition(LaunchConfiguration('enable_plotter')),
        arguments=[
            '--topic-regex',
            LaunchConfiguration('plotter.topic_regex'),
            '--field',
            LaunchConfiguration('plotter.field'),
            '--sensor-qos',
        ],
    )
    thermal = Node(
        package='axiom_thermal_viz',
        executable='thermal_heatmap',
        namespace=LaunchConfiguration('namespace'),
        output='screen',
        condition=IfCondition(LaunchConfiguration('enable_thermal')),
        parameters=[{'input_topic': LaunchConfiguration('thermal.input_topic')}],
    )
    rqt = Node(
        package='rqt_gui',
        executable='rqt_gui',
        output='screen',
        condition=IfCondition(LaunchConfiguration('enable_rqt')),
    )
    return LaunchDescription(arguments + [driver, plotter, thermal, rqt])
