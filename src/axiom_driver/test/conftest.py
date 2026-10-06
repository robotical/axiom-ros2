"""Pure client tests also run without sourcing a ROS installation."""

import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


@pytest.fixture
def catalogue():
    fixture = Path(__file__).parent / 'fixtures' / 'firmware_catalogue.json'
    return json.loads(fixture.read_text())['records']
