"""Exercise gesture discrimination, sample timing and recovery using motion traces."""

import math

from axiom_shake_detector.detector import ShakeDetector
import pytest


def trace(detector, duration, acceleration, start=0, rate=100):
    return [
        detector.update(start + i / rate, acceleration(i / rate))
        for i in range(round(duration * rate))
    ]


def test_still_board_and_slow_tilt_do_not_trigger():
    detector = ShakeDetector()
    rows = trace(detector, 5, lambda t: (0.03 * math.sin(t * 20), 0, 9.81))
    rows += trace(
        detector, 5, lambda t: (9.81 * math.sin(t * 0.1), 0, 9.81 * math.cos(t * 0.1)), start=5
    )
    assert not any(row.triggered for row in rows)
    assert rows[-1].ready


@pytest.mark.parametrize('rate', [50, 100, 200])
@pytest.mark.parametrize('axis', [0, 1, 2])
def test_repeated_shakes_on_each_axis_trigger_at_various_rates(rate, axis):
    detector = ShakeDetector()
    trace(detector, 1, lambda t: (0, 0, 9.81), rate=rate)

    def shake(t):
        values = [0, 0, 9.81]
        values[axis] += 7 * math.sin(2 * math.pi * 4 * t)
        return values

    rows = trace(detector, 3, shake, start=1, rate=rate)
    events = [1 + i / rate for i, row in enumerate(rows) if row.triggered]
    assert 1 <= len(events) <= 2
    assert all(b - a >= 1.5 for a, b in zip(events, events[1:]))


def test_one_bump_is_not_a_shake():
    detector = ShakeDetector()
    rows = trace(detector, 3, lambda t: (8 if 1 < t < 1.08 else 0, 0, 9.81))
    assert not any(row.triggered for row in rows)


def test_gap_rewind_and_invalid_input_restart_filter_without_events():
    detector = ShakeDetector()
    trace(detector, 1, lambda t: (0, 0, 9.81))
    for stamp in (10, 5, 5):
        row = detector.update(stamp, (10, 0, 9.81))
        assert not row.ready and not row.triggered
    assert detector.update(6, (math.nan, 0, 9.81)) is None
    assert detector.update(6.1, (0, 0, 9.81)).motion == 0


def test_replaying_identical_timestamps_reproduces_events():
    times = [i / 100 for i in range(500)]
    samples = [(7 * math.sin(2 * math.pi * 4 * t) if 1 < t < 3 else 0, 0, 9.81) for t in times]
    results = []
    for _ in range(2):
        detector = ShakeDetector()
        results.append([t for t, a in zip(times, samples) if detector.update(t, a).triggered])
    assert results[0] and results[0] == results[1]


@pytest.mark.parametrize(
    'settings',
    [
        {'threshold': -1},
        {'release': 4},
        {'window': 0},
        {'min_pulses': 1},
        {'min_pulses': 2.5},
        {'cooldown': math.nan},
    ],
)
def test_invalid_configuration_rejected(settings):
    with pytest.raises(ValueError):
        ShakeDetector(**settings)
