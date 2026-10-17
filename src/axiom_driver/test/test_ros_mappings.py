"""Optional mapping schema, unit compatibility and invalid scalar readings."""

import math

from axiom_driver.core.decoding import SampleDecoder
from axiom_driver.core.ros_mappings import mapped_scalar_output, parse_ros_mappings
import pytest


def metadata(block):
    return {'resp': {'a': [{'n': 'light'}, {'n': 'other'}]}, 'ros': block}


def test_no_mapping_is_an_unchanged_default():
    assert parse_ros_mappings({'resp': {'a': [{'n': 'light'}]}}) == ({}, [])


@pytest.mark.parametrize('block', [
    None, False, [], '', {},
    {'version': True, 'attributes': {}}, {'version': 1., 'attributes': {}},
    {'version': 2, 'attributes': {}}, {'version': 1},
    {'version': 1, 'attributes': []}, {'version': 1, 'attributes': None},
    {'version': 1, 'attributes': {}, 'typo': True},
])
def test_invalid_block_warns_and_selects_no_overrides(block):
    mappings, warnings = parse_ros_mappings(metadata(block))
    assert mappings == {} and len(warnings) == 1


@pytest.mark.parametrize('declaration', [
    None, [], {}, 'std_msgs/msg/Float64',
    {'message_type': []}, {'message_type': 'other/msg/Executable'},
    {'message_type': 'Float64'}, {'message_type': 'std_msgs/msg/Float64', 'scale': 2},
])
def test_bad_entry_does_not_disable_valid_peers(declaration):
    mappings, warnings = parse_ros_mappings(metadata({'version': 1, 'attributes': {
        'light': {'message_type': 'sensor_msgs/msg/Illuminance'}, 'other': declaration}}))
    assert mappings == {'light': 'sensor_msgs/msg/Illuminance'}
    assert len(warnings) == 1 and 'other' in warnings[0]


def test_unknown_attribute_is_reported_without_losing_known_entries():
    mappings, warnings = parse_ros_mappings(metadata({'version': 1, 'attributes': {
        'light': {'message_type': 'sensor_msgs/msg/Illuminance'},
        'typo': {'message_type': 'std_msgs/msg/Float64'}}}))
    assert mappings == {'light': 'sensor_msgs/msg/Illuminance'}
    assert warnings == ['ros.attributes.typo: attribute is not in resp.a']


@pytest.mark.parametrize('message_type,unit,reading,expected', [
    ('sensor_msgs/msg/Illuminance', 'lux', 12.5, ('illuminance', 12.5, 'lux')),
    ('sensor_msgs/msg/Temperature', '&deg;C', -12.5, ('temperature', -12.5, 'degC')),
    ('sensor_msgs/msg/RelativeHumidity', '%RH', 42., ('humidity', .42, 'fraction')),
    ('std_msgs/msg/Float64', 'mV', 12.5, ('float', .0125, 'V')),
    ('std_msgs/msg/Float64', 'index', 2., ('float', 2., 'index')),
])
def test_mapping_uses_engineering_or_si_values_without_reapplying_transforms(
    message_type, unit, reading, expected,
):
    entry = SampleDecoder.entry(1000, reading,
                                {'n': 'unfamiliar', 't': '<H', 'u': unit, 'd': 24}, '')
    assert mapped_scalar_output(message_type, entry) == expected


@pytest.mark.parametrize('message_type,unit', [
    ('sensor_msgs/msg/Illuminance', 'index'),
    ('sensor_msgs/msg/Temperature', 'lux'),
    ('sensor_msgs/msg/RelativeHumidity', 'index'),
])
def test_a_declaration_cannot_invent_a_unit_conversion(message_type, unit):
    entry = SampleDecoder.entry(2, 2., {'n': 'value', 't': 'f', 'u': unit}, '')
    with pytest.raises(ValueError, match='normalised'):
        mapped_scalar_output(message_type, entry)


@pytest.mark.parametrize('message_type,attr,value', [
    ('std_msgs/msg/Bool', {'n': 'reading', 't': 'B', 'o': 'bool'}, True),
    ('std_msgs/msg/String', {'n': 'reading', 't': '4s'}, b'abc\0'),
])
def test_invalid_bool_and_text_keep_their_mapping_without_a_numeric_substitute(
    message_type, attr, value,
):
    entry = SampleDecoder.entry(value, value, attr, '')
    output = mapped_scalar_output(message_type, entry)
    assert output[1] == (True if message_type.endswith('/Bool') else 'abc')
    entry.update(valid=False, value=math.nan)
    assert mapped_scalar_output(message_type, entry) is None


@pytest.mark.parametrize('message_type,attr,value', [
    ('std_msgs/msg/Bool', {'n': 'reading', 't': 'H'}, 2),
    ('std_msgs/msg/Float64', {'n': 'reading', 't': 'B', 'o': 'bool'}, True),
    ('std_msgs/msg/Float64', {'n': 'reading', 't': '4s'}, b'abc\0'),
    ('std_msgs/msg/String', {'n': 'reading', 't': 'f'}, 2.),
    ('std_msgs/msg/Float64', {'n': 'reading', 't': 'H[2]'}, [1, 2]),
])
def test_incompatible_shapes_and_native_types_are_rejected(message_type, attr, value):
    entry = SampleDecoder.entry(value, value, attr, '')
    with pytest.raises(ValueError, match='scalar attribute'):
        mapped_scalar_output(message_type, entry)


@pytest.mark.parametrize('reading', [-1., math.nan, math.inf, -math.inf])
def test_mapped_illuminance_marks_unavailable_or_negative_readings(reading):
    entry = SampleDecoder.entry(reading, reading, {'n': 'light', 't': 'f', 'u': 'lux'}, '')
    kind, value, unit = mapped_scalar_output('sensor_msgs/msg/Illuminance', entry)
    assert kind == 'illuminance' and math.isnan(value) and unit == 'lux'
