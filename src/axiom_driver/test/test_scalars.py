"""Descriptor-driven scalar contracts without ROS or connected hardware."""

import math
import struct

from axiom_driver.core.decoding import SampleDecoder
from axiom_driver.core.scalars import scalar_output
from axiom_driver.core.topic_names import attribute_topic
import pytest


def test_ltr390_uses_engineering_values_once_and_keeps_uvi_unit(catalogue):
    values = SampleDecoder().values(bytes.fromhex('7d00003000'),
                                    catalogue['LTR-390']['resp'], 'LTR-390')[0][0]
    assert values['ambient']['raw'] == 125
    assert scalar_output('ambient', values['ambient']) == ('illuminance', 100.0, 'lux')
    assert values['UVI']['raw'] == 48
    assert values['UVI']['si_value'] is None
    assert scalar_output('UVI', values['UVI']) == ('float', 2.0, 'index')


def test_light_mapping_is_not_model_specific_or_inferred_from_lux_alone(catalogue):
    decoder = SampleDecoder()
    values = decoder.values(struct.pack('<3H', 5, 100, 200),
                            catalogue['VCNL4040']['resp'], 'VCNL4040')[0][0]
    assert scalar_output('als', values['als'])[0] == 'illuminance'
    assert scalar_output('white', values['white'])[0] == 'illuminance'
    assert scalar_output('prox', values['prox']) == ('float', 5.0, None)
    values = decoder.values(struct.pack('<2H', 100, 300),
                            catalogue['LTR-329']['resp'], 'LTR-329')[0][0]
    assert scalar_output('visible', values['visible']) == ('illuminance', 200.0, 'lux')
    assert scalar_output('ir', values['ir']) == ('float', 100.0, 'lux')


@pytest.mark.parametrize('unit,expected,output_unit', [
    ('mV', .05, 'V'), ('mm', .05, 'm'), ('%', .5, 'fraction'),
    ('ppm', 50., 'ppm'), ('index', 50., 'index'), ('', 50., None),
])
def test_numeric_fallback_uses_si_or_engineering_with_no_raw_fallback(unit, expected, output_unit):
    entry = SampleDecoder.entry(100, 50., {'n': 'reading', 't': 'H', 'u': unit}, '')
    assert scalar_output('reading', entry) == ('float', expected, output_unit)


@pytest.mark.parametrize('reading', [-1., math.inf, -math.inf, math.nan])
def test_illuminance_never_publishes_negative_or_nonfinite_lux(reading):
    entry = SampleDecoder.entry(reading, reading, {'n': 'ambient', 't': 'f', 'u': 'lux'}, '')
    kind, value, unit = scalar_output('ambient', entry)
    assert kind == 'illuminance' and unit == 'lux' and math.isnan(value)


@pytest.mark.parametrize('fmt,storage,raw,expected', [
    ('B', 'bool', 1, ('bool', True, None)),
    ('?', None, False, ('bool', False, None)),
    ('6s', None, b'hello\0', ('string', 'hello', None)),
    ('s[6]', None, b'hello\0', ('string', 'hello', None)),
    ('c', None, b'A', ('string', 'A', None)),
    ('H', 'uint16', 125, ('float', 125., None)),
])
def test_invalid_first_sample_does_not_change_bool_text_or_numeric_contract(
    fmt, storage, raw, expected,
):
    attr = {'n': 'reading', 't': fmt, 'o': storage, 'vft': 'valid'}
    valid = {'n': 'valid', 't': 'B', 'o': 'bool'}
    row = {'reading': SampleDecoder.entry(raw, raw, attr, ''),
           'valid': SampleDecoder.entry(0, 0, valid, '')}
    SampleDecoder.validate(row, [attr, valid])
    output = scalar_output('reading', row['reading'])
    if expected[0] == 'float':
        assert output[0] == 'float' and math.isnan(output[1])
    else:
        assert output is None
    assert scalar_output('reading', SampleDecoder.entry(raw, raw, attr, '')) == expected


@pytest.mark.parametrize('raw', [[1, 2], (1, 2), {'x': 1}])
def test_structured_values_do_not_become_scalars(raw):
    entry = {'raw': raw, 'value': raw, 'meta': {'n': 'pixels', 't': 'B[2]'}}
    assert scalar_output('pixels', entry) is None


def test_bracket_text_format_decodes_to_a_scalar_string():
    values = SampleDecoder().values(b'hello\0', {'a': [{'n': 'label', 't': 's[6]'}]})[0][0]
    assert scalar_output('label', values['label']) == ('string', 'hello', None)


def test_attribute_names_are_visible_injective_and_keep_case():
    names = ['ambient', 'UVI', 'data', 'image', '1st', '_hidden', 'A/B', 'A_B', '温度',
             'attribute_data', 'attribute_image', 'data_raw', 'data_5fraw']
    topics = [attribute_topic(name) for name in names]
    assert topics[:4] == ['ambient', 'UVI', 'attribute_data', 'attribute_image']
    assert len(set(topics)) == len(names)
    assert all(topic[0].isalpha() and topic.isascii() and '/' not in topic for topic in topics)
