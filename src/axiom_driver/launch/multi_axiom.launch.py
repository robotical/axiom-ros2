"""Launch one isolated driver per configured board, without connecting it."""

import json
from pathlib import Path

from axiom_driver.config import DEFAULT_PARAMETERS
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue
from launch_ros.substitutions import FindPackageShare
import yaml


def boards(context):
    config = yaml.safe_load(Path(LaunchConfiguration('boards_file').perform(context)).read_text())
    rows = config.get('axioms') if isinstance(config, dict) else None
    if not isinstance(rows, dict) or not rows:
        raise ValueError('boards_file must contain a nonempty axioms mapping')
    nodes, names, frames, connections = [], set(), set(), set()
    for namespace, values in rows.items():
        name = '/' + str(namespace).strip('/')
        if not isinstance(values, dict) or set(values) - DEFAULT_PARAMETERS.keys():
            raise ValueError(f'Invalid driver parameters for {name}')
        params = {**DEFAULT_PARAMETERS, 'frame_id': name.strip('/').replace('/', '_'), **values}
        frame = params['frame_id']
        connection = (params['transport'], params['serial.port']
                      if params['transport'] == 'serial' else params['device_uri'])
        if name in names or frame in frames or connection in connections:
            raise ValueError('Each board needs a unique namespace, frame_id and connection')
        names.add(name)
        frames.add(frame)
        connections.add(connection)
        for key in ('topic_aliases', 'sensor_frames', 'sensor_qos.overrides'):
            if isinstance(params[key], dict):
                params[key] = json.dumps(params[key])
        params = {key: ParameterValue(value, value_type=type(DEFAULT_PARAMETERS[key]))
                  for key, value in params.items()}
        nodes.append(Node(package='axiom_driver', executable='axiom_bridge_node',
                          name='axiom_bridge_node', namespace=name, parameters=[params],
                          output='screen'))
    return nodes


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('boards_file', default_value=PathJoinSubstitution([
            FindPackageShare('axiom_driver'), 'config', 'two_axioms.yaml'])),
        OpaqueFunction(function=boards),
    ])
