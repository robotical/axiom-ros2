"""Launch one board, with a parameter file and typed command-line overrides."""

from axiom_driver.config import DEFAULT_PARAMETERS
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def runtime_node(context):
    overrides = {}
    for name, default in DEFAULT_PARAMETERS.items():
        value = LaunchConfiguration(name).perform(context)
        if value == '':
            continue
        if isinstance(default, bool):
            if value.lower() not in ('true', 'false'):
                raise ValueError(f'{name} must be true or false')
            overrides[name] = value.lower() == 'true'
        else:
            overrides[name] = type(default)(value)
        # Keep JSON configuration strings as strings when launch evaluates YAML.
        overrides[name] = ParameterValue(overrides[name], value_type=type(default))
    return [
        Node(
            package='axiom_driver',
            executable='axiom_bridge_node',
            name='axiom_bridge_node',
            namespace=LaunchConfiguration('namespace'),
            parameters=[LaunchConfiguration('params_file'), overrides],
            output='screen',
        )
    ]


def generate_launch_description():
    arguments = [
        DeclareLaunchArgument('namespace', default_value='axiom'),
        DeclareLaunchArgument(
            'params_file',
            default_value=PathJoinSubstitution(
                [FindPackageShare('axiom_driver'), 'config', 'axiom.yaml']
            ),
        ),
    ]
    for name in DEFAULT_PARAMETERS:
        arguments.append(
            DeclareLaunchArgument(
                name,
                default_value='',
                description='Override the parameter file value',
            )
        )
    return LaunchDescription(arguments + [OpaqueFunction(function=runtime_node)])
