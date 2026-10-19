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
        'commands': [{'name': a['n'], 'service': topic + '/commands/' + a['n'],
                      'descriptor': a} for a in profile['actions']],
    }
