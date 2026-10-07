"""Launch one isolated driver per configured board using its startup parameters."""

from axiom_driver.config import DEFAULT_PARAMETERS, load_boards
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import EnvironmentVariable, LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare


def boards(context):
    nodes = []
    for name, params in load_boards(LaunchConfiguration('boards_file').perform(context)).items():
        params = {key: ParameterValue(value, value_type=type(DEFAULT_PARAMETERS[key]))
                  for key, value in params.items()}
        nodes.append(Node(package='axiom_driver', executable='axiom_bridge_node',
                          name='axiom_bridge_node', namespace=name, parameters=[params],
                          output='screen'))
    return nodes


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('boards_file', default_value=EnvironmentVariable(
            'AXIOM_ROS_BOARDS_FILE', default_value=PathJoinSubstitution([
                FindPackageShare('axiom_driver'), 'config', 'two_axioms.yaml']))),
        OpaqueFunction(function=boards),
    ])
