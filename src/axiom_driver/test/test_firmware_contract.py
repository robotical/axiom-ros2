"""Golden payload regressions using the checked-in Axiom firmware catalogue."""

import math
import struct

from axiom_driver.core.custom import crc8, DecodeError
from axiom_driver.core.decoding import SampleDecoder
from axiom_driver.core.registry import DeviceKey, DeviceRegistry, parse_devjson, topic_token
from axiom_driver.core.timing import DeviceTimeline, Receipt
from axiom_driver.core.units import to_si
import pytest


def decode(catalogue, name, payload):
    meta = catalogue[name]['resp']
    payload = payload.ljust(meta['b'], b'\0')
    return SampleDecoder().blocks((b'\0\x64' + payload).hex(), meta, name)


def test_current_envelope_and_legacy_identity():
    current = parse_devjson(
        {'_v': 1, '_t': 0, '1': {'038': {'_i': 3, '_o': 1, 'x': '006407'}, '_s': {'status': 1}}}
    )
    assert current[0].key == DeviceKey('1', '38')
    assert current[0].type_ref == 3
    legacy = parse_devjson({'I2C': {'38': {'_t': 'AHT20', 'x': '006407'}}})
    assert legacy[0].type_ref == 'AHT20'
    assert 'addr=0x38' in current[0].key.metadata_path


@pytest.mark.parametrize(
    'data',
    [{'_v': 2}, {'_v': True}, {'1': {'38': {'_i': True}}}, {'1': {'38': {'_i': 1, '_o': 7}}}],
)
def test_unsupported_envelopes_are_errors(data):
    with pytest.raises(DecodeError):
        parse_devjson(data)


def test_names_cannot_collide():
    assert topic_token('LTR-329') != topic_token('LTR_2d329')
    assert DeviceKey('1', '38').topic != DeviceKey('2', '38').topic


def test_registry_lifecycle_and_stale_metadata(catalogue):
    registry = DeviceRegistry(pending_bytes=8)
    record = parse_devjson({'1': {'38': {'_i': 3, '_o': 1, 'x': '006407'}}})[0]
    device, changed = registry.observe(record, 1.0)
    assert changed
    old_revision = device.revision
    registry.defer(device, record, Receipt(1, 1))
    registry.defer(device, record, Receipt(2, 2))
    assert device.dropped == 1 and len(device.pending) == 1
    response = {'rslt': 'ok', 'dtIdx': 3, 'devinfo': catalogue['AHT20'], 'name': 'room'}
    assert registry.install(record.key, old_revision, response)
    assert device.name == 'room'
    assert registry.take_pending(device)[0][1].ros_ns == 2
    record.online = 0
    assert not registry.observe(record, 3)[0].online
    record.online = 1
    device, changed = registry.observe(record, 4)
    assert changed and not device.metadata
    assert not registry.install(record.key, old_revision, response)
    record.online = 2
    assert registry.observe(record, 5) == (None, True)
    assert not registry.devices


def test_servo_preserves_scaled_fraction(catalogue):
    blocks = decode(catalogue, 'RoboticalServo', struct.pack('>hbbh', 123, -2, 1, 15))
    values = blocks[0][1][0]
    assert values['angle']['raw'] == 123
    assert values['angle']['value'] == 12.3
    assert values['angle']['si_value'] == pytest.approx(math.radians(12.3))


def test_lsm6ds_fifo_signed_scaling_and_sample_rows(catalogue):
    payload = bytes([12, 0, 0, 0]) + struct.pack(
        '<12h', -16384, 8192, 0, -8192, 0, 8192, 16384, 0, 0, 0, 8192, 0
    )
    block = decode(catalogue, 'LSM6DS', payload)[0]
    assert block[0] == 100
    assert len(block[1]) == 2
    assert block[1][0]['gx']['value'] == -1000
    assert block[1][0]['az']['si_value'] == 9.80665
    assert block[1][1]['gx']['si_value'] == pytest.approx(math.radians(1000))


def test_lsm6ds_alignment_and_truncation(catalogue):
    meta = catalogue['LSM6DS']['resp']
    # Pattern 5: discard one word before the complete six-axis sample.
    payload = bytes([7, 0, 5, 0]) + struct.pack('<7h', 999, 1, 2, 3, 4, 5, 6)
    rows, _ = SampleDecoder().values(payload, meta)
    assert rows[0]['gx']['raw'] == 1
    with pytest.raises(DecodeError):
        SampleDecoder().values(payload[:-1], meta)


@pytest.mark.parametrize(
    'mode,channel,values', [(1, 0, (1234, -2000, 3000, -123)), (2, 2, (0, 0, -1234, 0))]
)
def test_vcp_fifo(catalogue, mode, channel, values):
    raw = struct.pack('>4h', *values) if mode == 1 else struct.pack('>h', values[channel])
    block = decode(catalogue, 'RoboticalVCP', bytes([1, mode, channel, 2]) + raw)[0]
    assert block[2] == 2
    row = block[1][0]
    assert [row[n]['value'] for n in ('V1', 'V2', 'V3', 'I')] == [v / 1000 for v in values]


def test_vcp_rejects_bad_count(catalogue):
    with pytest.raises(DecodeError):
        decode(catalogue, 'RoboticalVCP', bytes([255, 1, 0, 0]))


def test_max30101_bounded_fifo(catalogue):
    block = decode(catalogue, 'MAX30101', bytes([1, 0, 0, 0, 1, 2, 0, 3, 4]))[0]
    assert block[1][0]['Red']['value'] == 258
    assert block[1][0]['IR']['value'] == 772
    assert len(decode(catalogue, 'MAX30101', bytes([31, 0, 0]))[0][1]) == 8


def test_scd40_wire_words_crc_and_scaling(catalogue):
    payload = b''
    for word in (500, 32768, 32768):
        raw = word.to_bytes(2, 'big')
        payload += raw + bytes([crc8(raw)])
    assert crc8(bytes.fromhex('beef')) == 0x92
    row = decode(catalogue, 'SCD40', payload)[0][1][0]
    assert row['CO2']['value'] == 500
    assert row['temperature']['value'] == pytest.approx(42.5013351644)
    assert row['humidity']['si_value'] == pytest.approx(32768 / 65535)
    with pytest.raises(DecodeError, match='CRC'):
        decode(catalogue, 'SCD40', payload[:-1] + bytes([payload[-1] ^ 1]))


def test_other_custom_calculations(catalogue):
    oxygen = decode(catalogue, 'GravityO2', bytes([120, 0, 0]))[0][1][0]
    assert oxygen['oxygen']['value'] == 20.9
    light = decode(catalogue, 'LTR-329', struct.pack('<HH', 40000, 50000))[0][1][0]
    assert light['ir']['value'] == 40000
    assert light['visible']['value'] == 10000


def test_weight_is_mass_and_ambiguous_units_are_not_guessed(catalogue):
    row = decode(catalogue, 'M5-Weight', struct.pack('<fI', 100, 1))[0][1][0]
    assert row['weight']['si_unit'] == 'kg'
    assert row['weight']['si_value'] == pytest.approx(0.1)
    assert to_si(100, 'g', attribute='unknown') == (None, None)


def test_invalid_range_retains_raw_and_validity(catalogue):
    row = decode(catalogue, 'VL53L4CD', bytes([4, 0, 100]))[0][1][0]
    assert row['valid']['value'] is False
    assert row['dist']['raw'] == 100
    assert row['dist']['valid'] is False
    assert math.isnan(row['dist']['value'])


def test_array_is_one_sample_not_64_fifo_samples(catalogue):
    row = decode(catalogue, 'AMG8833', struct.pack('<64h', *([100] * 64)))[0][1]
    assert len(row) == 1
    assert len(next(iter(row[0].values()))['value']) == 64


def test_thermal_negative_pixel_and_aht20_bitfields(catalogue):
    thermal = decode(catalogue, 'AMG8833', struct.pack('<64h', *([0x0FFF] * 64)))[0][1][0]
    assert thermal['temperature']['value'] == [-0.25] * 64
    # 50 %RH and 25 C: humidity and temperature are packed 20-bit counters.
    packed = (524288 << 20) | 393216
    row = decode(catalogue, 'AHT20', bytes([0]) + packed.to_bytes(5, 'big'))[0][1][0]
    assert row['humidity']['value'] == 50
    assert row['humidity']['si_value'] == 0.5
    assert row['temperature']['value'] == 25


def test_custom_source_change_requires_review(catalogue):
    import copy

    meta = copy.deepcopy(catalogue['LSM6DS']['resp'])
    meta['c']['c'] += 'out.gx=123;'
    with pytest.raises(DecodeError, match='contract changed'):
        SampleDecoder().values(bytes(meta['b']), meta)


def test_all_ordinary_catalogue_layouts_fit_the_declared_block(catalogue):
    checked = []
    for name, info in catalogue.items():
        metadata = info.get('resp', {})
        if metadata and not metadata.get('c'):
            rows, _ = SampleDecoder().values(bytes(metadata['b']), metadata, name)
            assert set(rows[0]) == {a['n'] for a in metadata['a']}, name
            checked.append(name)
    assert len(checked) == 39


def test_framing_is_not_guessed(catalogue):
    meta = catalogue['VL53L4CD']['resp']
    with pytest.raises(DecodeError, match='Truncated'):
        SampleDecoder().blocks('000000', meta)
    altered = dict(meta, c={'n': 'uninstalled_decoder'})
    with pytest.raises(DecodeError, match='Unsupported custom'):
        SampleDecoder().blocks('0000000000', altered)


def test_absolute_fields_cannot_read_outside_poll():
    meta = {'b': 1, 'a': [{'n': 'bad', 't': '>H', 'at': [0, 2]}]}
    with pytest.raises(DecodeError):
        SampleDecoder().values(b'\0', meta)


def test_timestamp_units_wrap_and_fifo_spacing():
    timeline = DeviceTimeline()
    receipt = Receipt(1.0, 10_000_000_000)
    first = timeline.stamp([(65530, [{'x': 1}], 0)], receipt)[0]
    assert first['timestamp_us'] == 6_553_000
    second = timeline.stamp([(4, [{'x': 2}, {'x': 3}], 0)], Receipt(1.001, 10_001_000_000), 100)
    assert [r['timestamp_us'] for r in second] == [6_553_900, 6_554_000]
    assert second[-1]['stamp_ns'] == 10_001_000_000
    assert second[0]['stamp_ns'] < second[1]['stamp_ns']
    assert second[0]['time_quality'] == 'fifo_estimated'
    assert DeviceTimeline().stamp([(100, [{}], 0)], receipt)[0]['timestamp_us'] == 10_000


def test_clock_gap_reboot_and_ros_jump_are_visible():
    clock = DeviceTimeline()
    clock.stamp([(100, [{}], 0)], Receipt(1, 1_000_000_000))
    assert (
        clock.stamp([(5, [{}], 0)], Receipt(2, 2_000_000_000))[0]['time_quality']
        == 'uncertain_gap'
    )
    assert (
        clock.stamp([(6, [{}], 0)], Receipt(20, 20_000_000_000))[0]['time_quality']
        == 'uncertain_gap'
    )
    assert clock.stamp([(7, [{}], 0)], Receipt(21, 0))[0]['time_quality'] == 'ros_clock_reset'


def test_latest_poll_anchors_a_buffered_message():
    rows = DeviceTimeline().stamp([(100, [{}], 0), (200, [{}], 0)], Receipt(1, 1_000_000_000))
    assert rows[0]['stamp_ns'] == 990_000_000
    assert rows[1]['stamp_ns'] == 1_000_000_000
