"""Run pure controller checks without requiring a ROS installation."""

import json
from pathlib import Path
import sys

import pytest

root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root / 'axiom_servo_demo'), str(root / 'axiom_driver')]


@pytest.fixture
def device():
    """Build public inventory using the checked-in Solo Servo descriptor."""
    path = root / 'axiom_driver/test/fixtures/firmware_catalogue.json'
    profile = json.loads(path.read_text())['records']['RoboticalSoloServo']
    topic = 'roboticalsoloservo_b1_10'
    return {
        'topic': topic, 'revision': 7, 'online': True, 'stale': False, 'metadata_ready': True,
        'command_topics': [{'name': 'angle', 'topic': topic + '/commands/angle',
                            'kind': 'angle', 'message_type': 'std_msgs/msg/Float64',
                            'unit': 'rad', 'descriptor': profile['actions'][0]}],
        'commands': [{'name': 'enable', 'service': topic + '/commands/enable',
                      'descriptor': profile['actions'][1]}],
    }
