"""Check that the standalone model contains only the right leg and its linkage."""

from pathlib import Path
import xml.etree.ElementTree as ET

SHARE = Path(__file__).resolve().parents[1]


def test_right_leg_has_one_controlled_axis_and_connected_geometry():
    """Keep hip-coupled links moving and other axes fixed without a Marty dependency."""
    robot = ET.parse(SHARE / 'urdf/right_leg.urdf').getroot()
    links = {link.get('name') for link in robot.findall('link')}
    joints = robot.findall('joint')
    assert len(links) == 11
    assert links == {'axiom_servo_demo_base', 'hip_right', 'foot_right'} | {
        'leg_right_' + part for part in (
            'thigh_front', 'thigh_back', 'knee_upper', 'twist_upper',
            'twist_lower', 'knee_lower', 'shin_exterior', 'shin_interior')}
    assert len(joints) == len(links) - 1
    assert {joint.find('child').get('link') for joint in joints} == (
        links - {'axiom_servo_demo_base'})
    assert all(joint.find('parent').get('link') in links for joint in joints)
    independent = [joint for joint in joints
                   if joint.get('type') != 'fixed' and joint.find('mimic') is None]
    assert [joint.get('name') for joint in independent] == ['servo_joint']
    assert independent[0].find('axis').get('xyz') == '0 1 0'
    mimic = {joint.get('name'): joint.find('mimic') for joint in joints
             if joint.find('mimic') is not None}
    assert {name: float(value.get('multiplier')) for name, value in mimic.items()} == {
        'leg_right_thigh_back_joint': 1, 'leg_right_knee_upper_joint': -1}
    assert all(value.get('joint') == 'servo_joint' for value in mimic.values())
    for mesh in robot.findall('.//mesh'):
        uri = mesh.get('filename')
        assert uri.startswith('package://axiom_servo_demo/')
        assert (SHARE / uri.removeprefix('package://axiom_servo_demo/')).is_file()
