"""Measurement validation shared by the read-only RViz adapters."""

from dataclasses import dataclass
import math


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def range_value(value, minimum, maximum):
    if not all(finite(v) for v in (value, minimum, maximum)):
        raise ValueError("Range reading unavailable")
    if minimum < 0 or maximum <= minimum or not minimum <= value <= maximum:
        raise ValueError("Range reading outside sensor limits")
    return float(value)


@dataclass
class Reading:
    value: object = None
    valid: bool = False
    stamp_ns: int = 0
    seen: float = 0.0
    error: str = "Waiting for measurements"

    def update(self, stamp_ns, now_ns, now, value=None, error="", stale_after=1.5):
        # Replayed/duplicate stamps never refresh the receive watchdog.
        if stamp_ns <= 0 or not -0.25 <= (now_ns - stamp_ns) / 1e9 <= stale_after:
            self.valid, self.error = False, "Measurement timestamp is stale or invalid"
            return False
        if stamp_ns == self.stamp_ns:
            return False
        if stamp_ns < self.stamp_ns:
            self.reset("Sensor clock changed; wait for new measurements")
            return False
        self.stamp_ns = stamp_ns
        if error:
            self.valid, self.error = False, error
            return False
        self.value, self.valid, self.seen, self.error = value, True, now, ""
        return True

    def fresh(self, now, timeout=1.5):
        return self.valid and now - self.seen <= timeout

    def reset(self, reason="Sensor disconnected"):
        self.value, self.valid, self.stamp_ns, self.seen = None, False, 0, 0.0
        self.error = reason
