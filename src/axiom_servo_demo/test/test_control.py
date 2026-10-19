"""Exercise actual descriptor encoding, selection and command gating."""

import copy
import math

from axiom_servo_demo.control import command_value, joint_position, select_servo, TargetGate
import pytest


def test_selection_is_explicit_when_ambiguous_and_ignores_unavailable_devices(device):
    """Require an exact selector for multiple devices and track replacements."""
    binding = select_servo([device])
    assert binding.angle_service.endswith('/commands/angle')
    assert binding.enable_service.endswith('/commands/enable')
    other = copy.deepcopy(device)
    other['topic'] = 'other_servo'
    for item in other['commands']:
        item['service'] = 'other_servo/commands/' + item['name']
    with pytest.raises(ValueError, match='Multiple'):
        select_servo([device, other])
    assert select_servo([device, other], device['topic']) == binding
    for field, value in [('online', False), ('stale', True), ('metadata_ready', False)]:
        with pytest.raises(ValueError, match='Waiting'):
            select_servo([{**device, field: value}])
    assert select_servo([{**other, 'stale': True}, device]) == binding
    assert select_servo([{**device, 'revision': 8}]) != binding


def test_unsupported_or_unrelated_commands_are_not_selected(device):
    """Reject unsupported formats, bad scaling and services for another device."""
    for change in ({'t': 'hh'}, {'vt': 'custom'}, {'mul': 0}, {'mul': math.inf}):
        row = copy.deepcopy(device)
        row['commands'][0]['descriptor'].update(change)
        with pytest.raises(ValueError, match='Waiting'):
            select_servo([row])
    row = copy.deepcopy(device)
    row['commands'][0]['service'] = 'other_device/commands/angle'
    with pytest.raises(ValueError, match='Waiting'):
        select_servo([row])
    row = copy.deepcopy(device)
    row['commands'][0]['name'] = 'set angle'
    assert select_servo([row], angle_command='set angle').topic == device['topic']


def test_radians_are_rounded_to_descriptor_tenths_of_a_degree(device):
    """Validate both configured and advertised limits around wire quantization."""
    action = select_servo([device]).angle
    assert command_value(action, math.radians(-12.34), 'degrees', -1, 1) == -12.3
    assert command_value(action, 0.3, 'degrees', -1, 1) == 17.2
    assert command_value({'t': 'd'}, 0.3, 'radians', -1, 1) == 0.3
    for position in (math.nan, math.inf, -1.1, 1.1):
        with pytest.raises(ValueError):
            command_value(action, position, 'degrees', -1, 1)
    with pytest.raises(ValueError, match='descriptor limits'):
        command_value({**action, 'r': [-10, 10]}, 0.3, 'degrees', -1, 1)
    with pytest.raises(ValueError, match='Rounded'):
        command_value(action, math.radians(12.36), 'degrees', 0, math.radians(12.36))


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
