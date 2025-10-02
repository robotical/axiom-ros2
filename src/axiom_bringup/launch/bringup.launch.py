from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, IncludeLaunchDescription, OpaqueFunction
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch.conditions import IfCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch_ros.substitutions import FindPackageShare
from launch_ros.actions import Node

def _build_runtime_nodes(context, *args, **kwargs):
    # Resolve values at runtime
    sensor_qos = LaunchConfiguration('plotter.sensor_qos').perform(context).lower()
    topic_regex = LaunchConfiguration('plotter.topic_regex')
    field = LaunchConfiguration('plotter.field')
    discovery_interval = LaunchConfiguration('plotter.discovery_interval')
    history_sec = LaunchConfiguration('plotter.history_sec')
    rate_hz = LaunchConfiguration('plotter.rate_hz')
    qos_depth = LaunchConfiguration('plotter.qos_depth')

    plotter_args = [
        '--topic-regex', topic_regex,
        '--field', field,                     # your script ignores empty string
        '--discovery-interval', discovery_interval,
        '--history-sec', history_sec,
        '--rate-hz', rate_hz,
        '--qos-depth', qos_depth,
    ]
    # Only include --sensor-qos when true/1/yes
    if sensor_qos in ('true', '1', 'yes', 'on'):
        plotter_args.insert(0, '--sensor-qos')

    plotter_node = Node(
        condition=IfCondition(LaunchConfiguration('enable_plotter')),
        package='axiom_plotter',
        executable='dynamic_grapher',
        name='axiom_dynamic_plotter',
        output='screen',
        arguments=plotter_args,
    )

    rqt_node = Node(
        condition=IfCondition(LaunchConfiguration('enable_rqt')),
        package='rqt_gui',
        executable='rqt_gui',
        name='axiom_rqt',
        output='screen',
        arguments=['--standalone', LaunchConfiguration('rqt_plugin')],
    )

    return [plotter_node, rqt_node]

def generate_launch_description():
    # Driver args: pass-through to your axiom_driver/axiom_minimal_launch.py
    driver_args = [
        DeclareLaunchArgument('transport',    default_value='ws'),
        DeclareLaunchArgument('device_uri',   default_value='ws://192.168.1.7/devjson'),
        DeclareLaunchArgument('auto_connect', default_value='true'),
        DeclareLaunchArgument('frame_id',     default_value='axiom_link'),
        DeclareLaunchArgument('namespace',    default_value=''),

        DeclareLaunchArgument('serial.port',            default_value='/dev/cu.usbmodem2101'),
        DeclareLaunchArgument('serial.baud',            default_value='115200'),
        DeclareLaunchArgument('serial.timeout',         default_value='0.02'),
        DeclareLaunchArgument('serial.mode',            default_value='auto'),
        DeclareLaunchArgument('serial.autosub',         default_value='true'),
        DeclareLaunchArgument('serial.devjson_rate_hz', default_value='0.1'),

        DeclareLaunchArgument('use_dual_ws', default_value='true'),
        DeclareLaunchArgument('ws_path',     default_value='/ws'),
        DeclareLaunchArgument('ws_pcol',     default_value='RICSerial'),
    ]

    # Plotter args
    plotter_args = [
        DeclareLaunchArgument('enable_plotter',              default_value='true'),
        DeclareLaunchArgument('plotter.topic_regex',         default_value='/LSM6DS_76a/imu/data_raw'),
        DeclareLaunchArgument('plotter.field',               default_value='linear_acceleration.z'),
        DeclareLaunchArgument('plotter.discovery_interval',  default_value='2.0'),
        DeclareLaunchArgument('plotter.history_sec',         default_value='120.0'),
        DeclareLaunchArgument('plotter.rate_hz',             default_value='15.0'),
        DeclareLaunchArgument('plotter.sensor_qos',          default_value='true'),
        DeclareLaunchArgument('plotter.qos_depth',           default_value='50'),
    ]

    # RQt args
    rqt_args = [
        DeclareLaunchArgument('enable_rqt', default_value='false'),
        DeclareLaunchArgument('rqt_plugin', default_value='axiom_rqt_plugins/ConnectionPanel'),
    ]

    driver_launch = IncludeLaunchDescription(
        PythonLaunchDescriptionSource(
            PathJoinSubstitution([
                FindPackageShare('axiom_driver'),
                'launch',
                'axiom_minimal_launch.py'
            ])
        ),
        launch_arguments={
            'transport':    LaunchConfiguration('transport'),
            'device_uri':   LaunchConfiguration('device_uri'),
            'auto_connect': LaunchConfiguration('auto_connect'),
            'frame_id':     LaunchConfiguration('frame_id'),
            'namespace':    LaunchConfiguration('namespace'),
            'serial.port':  LaunchConfiguration('serial.port'),
            'serial.baud':  LaunchConfiguration('serial.baud'),
            'serial.timeout': LaunchConfiguration('serial.timeout'),
            'serial.mode':    LaunchConfiguration('serial.mode'),
            'serial.autosub': LaunchConfiguration('serial.autosub'),
            'serial.devjson_rate_hz': LaunchConfiguration('serial.devjson_rate_hz'),
            'use_dual_ws':  LaunchConfiguration('use_dual_ws'),
            'ws_path':      LaunchConfiguration('ws_path'),
            'ws_pcol':      LaunchConfiguration('ws_pcol'),
        }.items()
    )

    return LaunchDescription(
        driver_args + plotter_args + rqt_args + [
            driver_launch,
            OpaqueFunction(function=_build_runtime_nodes),
        ]
    )