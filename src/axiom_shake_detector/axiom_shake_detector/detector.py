"""Timestamp-driven shake heuristic, independent of ROS and wall-clock speed."""

from collections import deque
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Reading:
    motion: float
    triggered: bool
    pulses: int
    ready: bool


class ShakeDetector:
    """Detect several separated acceleration pulses after removing slow gravity."""

    def __init__(
        self,
        threshold=3.0,
        release=1.2,
        window=0.8,
        min_pulses=3,
        cooldown=1.5,
        gravity_tau=0.35,
        warmup=0.5,
        max_gap=0.5,
    ):
        numbers = (threshold, release, window, cooldown, gravity_tau, warmup, max_gap)
        if not all(math.isfinite(n) and n > 0 for n in numbers):
            raise ValueError('Detector times and thresholds must be finite and positive')
        if release >= threshold or type(min_pulses) is not int or min_pulses < 2:
            raise ValueError('Release must be below threshold; min_pulses must be >= 2')
        self.threshold, self.release, self.window = threshold, release, window
        self.min_pulses, self.cooldown = min_pulses, cooldown
        self.gravity_tau, self.warmup, self.max_gap = gravity_tau, warmup, max_gap
        self.reset()

    def reset(self):
        """Discard filter and gesture history after invalid data or a clock reset."""
        self.gravity = None
        self.last_time = None
        self.started = None
        self.high = False
        self.peaks = deque()
        self.last_peak = -math.inf
        self.last_event = -math.inf

    def update(self, stamp, acceleration):
        """Return motion and event state; reject invalid input instead of detecting."""
        if len(acceleration) != 3 or not all(math.isfinite(v) for v in (*acceleration, stamp)):
            self.reset()
            return None
        if self.last_time is not None:
            dt = stamp - self.last_time
            if dt <= 0 or dt > self.max_gap:
                self.reset()
        if self.gravity is None:
            self.gravity = tuple(acceleration)
            self.last_time = self.started = stamp
            return Reading(0.0, False, 0, False)
        dt = stamp - self.last_time
        self.last_time = stamp
        alpha = 1.0 - math.exp(-dt / self.gravity_tau)
        self.gravity = tuple(g + alpha * (a - g) for a, g in zip(acceleration, self.gravity))
        motion = math.sqrt(sum((a - g) ** 2 for a, g in zip(acceleration, self.gravity)))
        ready = stamp - self.started >= self.warmup
        while self.peaks and stamp - self.peaks[0] > self.window:
            self.peaks.popleft()
        if motion <= self.release:
            self.high = False
        if not ready or stamp - self.last_event < self.cooldown:
            self.peaks.clear()
            return Reading(motion, False, 0, ready)
        if motion >= self.threshold and not self.high:
            self.high = True
            # Avoid counting noise chatter as separate pulses.
            if stamp - self.last_peak >= 0.08:
                self.peaks.append(stamp)
                self.last_peak = stamp
        pulses = len(self.peaks)
        triggered = pulses >= self.min_pulses
        if triggered:
            self.last_event = stamp
            self.peaks.clear()
        return Reading(motion, triggered, pulses, ready)
