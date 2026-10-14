"""Range-grid validity, padding and standard image byte contracts."""

import copy
import math
import struct

from axiom_driver.core.decoding import SampleDecoder
from axiom_driver.core.grids import float32_image_data, zone_grid
import pytest


def grid_values(profiles, side=8):
    # Includes every accepted status, unknown/no-target statuses and signed data.
    distances = [1000, 2000, 3000, 4000, -50, 0] + list(range(1006, 1064))
    statuses = [5, 6, 9, 4, 5, 5] + [5] * 58
    statuses[6:8] = [255, 0]
    payload = (bytes([side, 17, 27, 3]) + struct.pack('<64h', *distances)
               + bytes(statuses))
    values = SampleDecoder().values(payload, profiles['VL53L5CX']['resp'], 'VL53L5CX')[0][0]
    return values


def test_range_wire_units_statuses_and_unchanged_raw(grid_profiles):
    values = grid_values(grid_profiles)
    before = copy.deepcopy(values)
    side, pixels = zone_grid(values, values['dist'])
    assert side == 8 and len(pixels) == 64
    assert pixels[:3] == [1.0, 2.0, 3.0]
    assert all(math.isnan(p) for p in pixels[3:8])
    assert pixels[-1] == pytest.approx(1.063)
    assert values == before  # Status masking is specific to the image output.


def test_four_by_four_excludes_reserved_padding(grid_profiles):
    values = grid_values(grid_profiles, side=4)
    side, pixels = zone_grid(values, values['dist'])
    assert side == 4 and len(pixels) == 16
    assert pixels[-1] == pytest.approx(1.015)
    assert len(float32_image_data(side, side, pixels)) == 64


@pytest.mark.parametrize('side', [0, 1, 4.5, True])
def test_reject_invalid_grid_dimensions(grid_profiles, side):
    values = grid_values(grid_profiles)
    values['grid']['value'] = side
    with pytest.raises(ValueError, match='4x4 or 8x8'):
        zone_grid(values, values['dist'])


@pytest.mark.parametrize('attribute', ['dist', 'status'])
def test_reject_truncated_grid(grid_profiles, attribute):
    values = grid_values(grid_profiles)
    field = 'si_value' if attribute == 'dist' else 'value'
    values[attribute][field] = values[attribute][field][:-1]
    with pytest.raises(ValueError, match='distances/statuses'):
        zone_grid(values, values['dist'])


def test_image_validity_and_nonfinite_ranges(grid_profiles):
    values = grid_values(grid_profiles)
    values['dist']['valid'] = [True] * 64
    values['dist']['valid'][0] = False
    values['dist']['si_value'][1] = math.inf
    values['dist']['si_value'][2] = math.nan
    assert all(math.isnan(p) for p in zone_grid(values, values['dist'])[1][:3])
    values['dist']['valid'] = False
    assert all(math.isnan(p) for p in zone_grid(values, values['dist'])[1])


def test_image_bytes_preserve_signed_temperature_and_missing_pixels():
    data = float32_image_data(3, 2, [-9.0, 0.0, 24.25, math.nan, math.inf, 1e100])
    assert data[:12] == bytes.fromhex('000010c1000000000000c241')
    assert all(math.isnan(p) for p in struct.unpack('<6f', data)[3:])
    with pytest.raises(ValueError, match='dimensions'):
        float32_image_data(2, 2, [1, 2, 3])
