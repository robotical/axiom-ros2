"""Exercise actual descriptor encoding, selection and command gating."""

import copy
import math

from axiom_servo_demo.control import joint_position, select_servo, TargetGate
import pytest


def test_selection_is_explicit_when_ambiguous_and_ignores_unavailable_devices(device):
    """Require an exact selector for multiple devices and track replacements."""
    binding = select_servo([device])
    assert binding.angle_topic.endswith('/commands/angle')
    assert binding.enable_service.endswith('/commands/enable')
    other = copy.deepcopy(device)
    other['topic'] = 'other_servo'
    for item in other['commands']:
        item['service'] = 'other_servo/commands/' + item['name']
    other['command_topics'][0]['topic'] = 'other_servo/commands/angle'
    with pytest.raises(ValueError, match='Multiple'):
        select_servo([device, other])
    assert select_servo([device, other], device['topic']) == binding
    for field, value in [('online', False), ('stale', True), ('metadata_ready', False)]:
        with pytest.raises(ValueError, match='Waiting'):
            select_servo([{**device, field: value}])
    assert select_servo([{**other, 'stale': True}, device]) == binding
    assert select_servo([{**device, 'revision': 8}]) != binding


def test_unsupported_or_unrelated_commands_are_not_selected(device):
    """Require the new radian topic contract and this device's enable service."""
    for change in ({'kind': 'other'}, {'unit': 'degrees'},
                   {'message_type': 'std_msgs/msg/String'}):
        row = copy.deepcopy(device)
        row['command_topics'][0].update(change)
        with pytest.raises(ValueError, match='Waiting'):
            select_servo([row])
    row = copy.deepcopy(device)
    row['command_topics'][0]['topic'] = 'other_device/commands/angle'
    with pytest.raises(ValueError, match='Waiting'):
        select_servo([row])
    row = copy.deepcopy(device)
    row['command_topics'][0]['name'] = 'set angle'
    assert select_servo([row]).topic == device['topic']


def test_joint_arrays_are_checked_and_other_joints_are_ignored():
    """Accept named positions only from correctly sized finite command arrays."""
    assert joint_position(['other', 'servo'], [0.1, 0.2], 'servo') == 0.2
    assert joint_position(['other'], [0.1], 'servo') is None
    for names, positions in [(['servo'], []), (['servo', 'servo'], [0., 1.]),
                             (['servo'], [math.nan])]:
        with pytest.raises(ValueError):
            joint_position(names, positions, 'servo')


def test_no_startup_or_enable_motion_and_newest_target_replaces_pending_values():
    """Require a new target after arming and replace unsent intermediate angles."""
    gate = TargetGate()
    gate.observe(0.)
    assert gate.next_target() is None
    gate.arm()
    gate.observe(0.)
    assert gate.next_target() is None
    gate.observe(10.)
    gate.observe(20.)
    assert gate.next_target() == 20.
    gate.sent(20.)
    assert gate.next_target() is None
    gate.observe(10.)
    assert gate.next_target() == 10.
    gate.disarm()
    assert gate.next_target() is None
    gate.observe(30.)
    gate.arm()
    assert gate.next_target() is None
    gate.observe(30.)
    assert gate.next_target() is None
    gate.observe(31.)
    assert gate.next_target() == 31.
