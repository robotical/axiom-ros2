"""Launch the same joint slider GUI as Marty and an Axiom service adapter."""

import math
from pathlib import Path
import xml.etree.ElementTree as ET

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def robot_description(share, model, lower, upper):
    """Load a packaged preview with the configured slider limits."""
    if model not in ('servo', 'right_leg'):
        raise ValueError('preview_model must be servo or right_leg')
    robot = ET.parse(share / 'urdf' / (model + '.urdf')).getroot()
    limit = robot.find("joint[@name='servo_joint']/limit")
    limit.set('lower', str(math.radians(lower)))
    limit.set('upper', str(math.radians(upper)))
    return {'robot_description': ET.tostring(robot, encoding='unicode')}


def demo_nodes(context):
    """Apply the same angle limits to the slider URDF and hardware adapter."""
    share = Path(get_package_share_directory('axiom_servo_demo'))
    lower = float(LaunchConfiguration('lower_limit_deg').perform(context))
    upper = float(LaunchConfiguration('upper_limit_deg').perform(context))
    if not math.isfinite(lower) or not math.isfinite(upper) or lower >= upper:
        raise ValueError('Demo angle limits must be finite with lower < upper')
    model = LaunchConfiguration('preview_model').perform(context)
    # The leg has one free joint; the GUI automatically follows its mimic joints.
    description = robot_description(share, model, lower, upper)
    adapter = {name: LaunchConfiguration(name).perform(context) for name in (
        'axiom_namespace', 'servo', 'angle_command', 'enable_command', 'command_unit')}
    adapter.update(lower_limit_deg=lower, upper_limit_deg=upper)
    adapter['command_rate_hz'] = float(LaunchConfiguration('command_rate_hz').perform(context))
    return [
        Node(package='axiom_servo_demo', executable='servo_adapter', namespace='servo_demo',
             output='screen', parameters=[adapter]),
        Node(package='joint_state_publisher_gui', executable='joint_state_publisher_gui',
             namespace='servo_demo', name='joint_controls', output='screen',
             parameters=[description], remappings=[('joint_states', 'joint_commands')],
             condition=IfCondition(LaunchConfiguration('gui'))),
        Node(package='robot_state_publisher', executable='robot_state_publisher',
             namespace='servo_demo', output='screen', parameters=[description],
             remappings=[('joint_states', 'joint_commands')]),
        Node(package='rviz2', executable='rviz2', name='servo_rviz', output='screen',
             arguments=['-d', str(share / 'config' / (model + '.rviz'))],
             condition=IfCondition(LaunchConfiguration('rviz'))),
    ]


def generate_launch_description():
    """Expose board/servo selection without starting a second Axiom driver."""
    defaults = {
        'axiom_namespace': ('/axiom', 'Namespace of the already-running Axiom driver'),
        'servo': ('', 'Exact relative device topic root; empty selects one unambiguous servo'),
        'angle_command': ('angle', 'Live descriptor action name for target angle'),
        'enable_command': ('enable', 'Live descriptor action name accepting 0/1'),
        'command_unit': ('degrees', 'Angle command units: degrees or radians'),
        'lower_limit_deg': ('-90.0', 'Lower demo angle limit in degrees'),
        'upper_limit_deg': ('90.0', 'Upper demo angle limit in degrees'),
        'command_rate_hz': ('10.0', 'Maximum angle command rate, up to 50 Hz'),
        'preview_model': ('servo', 'RViz target model: servo or right_leg'),
        'gui': ('true', 'Open the Marty-style joint slider window'),
        'rviz': ('true', 'Open the selected target preview in RViz'),
    }
    return LaunchDescription([
        *[DeclareLaunchArgument(name, default_value=value, description=description)
          for name, (value, description) in defaults.items()],
        OpaqueFunction(function=demo_nodes),
    ])
