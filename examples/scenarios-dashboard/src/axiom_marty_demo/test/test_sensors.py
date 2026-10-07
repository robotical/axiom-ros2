"""Measurement validation must reject invalid ranges and stale timestamps."""

import pytest

from axiom_marty_demo.sensors import Reading, range_value


def test_range_validity_and_units():
    assert range_value(0.3, 0, 1) == 0.3
    for value in (float("nan"), -1, 2):
        with pytest.raises(ValueError):
            range_value(value, 0, 1)


def test_duplicate_stale_and_out_of_order_readings_do_not_refresh():
    r = Reading()
    assert r.update(1_000_000_000, 1_000_000_000, 1, 0.3)
    assert not r.update(1_000_000_000, 1_100_000_000, 1.1, 0.4)
    assert r.seen == 1
    assert not r.update(900_000_000, 1_100_000_000, 1.2, 0.4)
    assert not r.valid
    assert not r.update(1_000_000_000, 5_000_000_000, 5, 0.4)
    assert not r.valid
