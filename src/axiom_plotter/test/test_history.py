"""History tracks sensor timestamps independently of rendering cadence."""

from axiom_plotter.history import TimeWindow


def test_history_duration_and_idle_expiration():
    history = TimeWindow(2)
    for sample in range(500):
        history.append(sample / 100, sample)
    assert len(history.data) == 201
    assert history.data[0][0] == 2.99
    assert history.prune(10) == []


def test_history_clock_reset_and_memory_limit():
    history = TimeWindow(100, max_points=3)
    for sample in range(5):
        history.append(sample, sample)
    assert len(history.data) == 3
    history.append(0, 99)
    assert list(history.data) == [(0, 99)]
