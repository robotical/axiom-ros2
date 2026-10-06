"""Bounded sensor history measured in seconds, independent of GUI refresh rate."""

from collections import deque


class TimeWindow:
    def __init__(self, seconds, max_points=100000):
        if seconds <= 0 or max_points < 1:
            raise ValueError('History duration and capacity must be positive')
        self.seconds = seconds
        self.data = deque(maxlen=max_points)

    def append(self, stamp, value):
        if self.data and stamp < self.data[-1][0]:
            self.data.clear()  # ROS clock reset or a new acquisition epoch.
        self.data.append((stamp, value))
        self.prune(stamp)

    def prune(self, now):
        cutoff = now - self.seconds
        while self.data and self.data[0][0] < cutoff:
            self.data.popleft()
        return list(self.data)
