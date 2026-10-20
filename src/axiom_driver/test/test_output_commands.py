"""Validate typed topic conversion against the actual servo and LED descriptors."""

import copy
import math

from axiom_driver.core.commands import encode_command
from axiom_driver.core.output_commands import output_topics, output_values
import pytest


def test_servo_radians_follow_descriptor_units_scaling_and_wire_limits(catalogue):
    metadata = catalogue['RoboticalServo']
    action = metadata['actions'][0]
    spec, = output_topics(metadata, action)
    values = output_values(action, spec, math.radians(-12.34))
    assert values == [-12.3]
    assert encode_command(action, values) == ['0001ff850064']
    assert output_values(action, spec, math.radians(180)) == [180.0]
    for angle in (math.nan, math.inf, math.radians(181)):
        with pytest.raises(ValueError):
            output_values(action, spec, angle)
    radian_action = {**action, 'u': 'radians', 't': 'd', 'r': [-1, 1], 'mul': 1}
    radians, = output_topics(metadata, radian_action)
    assert output_values(radian_action, radians, 0.25) == [0.25]


def test_new_servo_type_and_action_name_use_capabilities_not_a_type_allowlist(catalogue):
    metadata = copy.deepcopy(catalogue['RoboticalServo'])
    metadata['type'], metadata['clas'] = 'NewController', []
    action = metadata['actions'][0]
    action['n'] = 'set angle'
    assert output_topics(metadata, action)[0]['kind'] == 'angle'
    for change in ({'t': 'hh'}, {'vt': 'custom'}, {'mul': 0}, {'mul': math.inf}, {'u': 'steps'}):
        with pytest.raises(ValueError):
            output_topics(metadata, {**action, **change})
    assert output_topics(metadata, metadata['actions'][1]) == []


@pytest.mark.parametrize('device', ['QwiicLEDStick', 'RoboticalLEDRing'])
def test_normalized_rgb_addresses_each_pixel_and_preserves_wire_order(catalogue, device):
    metadata = catalogue[device]
    action = metadata['actions'][0]
    specs = output_topics(metadata, action)
    assert len(specs) == action['NX'] * action['NY']
    for index, spec in enumerate(specs):
        values = output_values(action, spec, (1.0, 0.0, 128 / 255))
        assert values == [index, 255, 0, 128]
        assert encode_command(action, values)[0].endswith(f'{index:02x}ff0080')
    for colour in ((-0.1, 0., 0.), (1.1, 0., 0.), (math.nan, 0., 0.)):
        with pytest.raises(ValueError):
            output_values(action, specs[0], colour)


def test_rgb_without_pixel_index_and_invalid_grids():
    action = {'n': 'colour', 't': '3B', 'w': 'aa'}
    spec, = output_topics({}, action)
    assert output_values(action, spec, (0., 1., 0.)) == [0, 255, 0]
    for count in (0, -1, 1025):
        with pytest.raises(ValueError):
            output_topics({}, {'n': 'pixels', 'f': 'LEDPIX', 't': 'BBBB', 'w': 'aa', 'NX': count})


@pytest.mark.parametrize('rgb,wire', [
    ((1., 0., 0.), 'b00000ff0000'), ((0., 1., 0.), 'b0000000ff00'),
    ((0., 0., 1.), 'b000000000ff'), ((18/255, 52/255, 86/255), 'b00000123456')])
def test_packed_rgb_preserves_fill_header_and_colour_order(ledstick, rgb, wire):
    action = next(a for a in ledstick['actions'] if a['n'] == 'colour')
    spec, = output_topics(ledstick, action)
    assert encode_command(action, output_values(action, spec, rgb)) == [wire]


@pytest.mark.parametrize('period', [0, 40, 250, 65535])
def test_stacklight_supported_format_uses_bottom_first_states(ledstick, period):
    action = next(a for a in ledstick['actions'] if a['n'] == 'stacklight')
    assert output_topics(ledstick, action) == []
    assert encode_command(action, [period, 0, 1, 6, 15]) == [f'4001{period:04x}0001060f']


@pytest.mark.parametrize('values', [
    [1, 0, 0, 0, 0], [39, 0, 0, 0, 0], [65536, 0, 0, 0, 0], [40.5, 0, 0, 0, 0],
    [250, -1, 0, 0, 0], [250, 16, 0, 0, 0], [250, .5, 0, 0, 0],
    [math.nan, 0, 0, 0, 0], [250, math.inf, 0, 0, 0], [250, 0, 0, 0]])
def test_stacklight_rejects_invalid_periods_states_and_arity(ledstick, values):
    action = next(a for a in ledstick['actions'] if a['n'] == 'stacklight')
    with pytest.raises(ValueError):
        encode_command(action, values)


def test_custom_value_formats_still_require_an_explicit_supported_contract(ledstick):
    action = next(a for a in ledstick['actions'] if a['n'] == 'stacklight')
    for change in ({'vt': 'unknown'}, {'f': 'OTHER'}, {'t': '<HBBBB'}, {'NY': 8}):
        with pytest.raises(ValueError, match='custom'):
            encode_command({**action, **change}, [250, 0, 0, 0, 0])
