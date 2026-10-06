"""Device clock unwrapping and explicitly estimated FIFO/ROS timestamps."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Receipt:
    monotonic: float
    ros_ns: int


class DeviceTimeline:
    """
    One timeline per device/group, discarded on session/profile changes.

    A 16-bit device counter cannot prove elapsed time over a long outage or distinguish every
    reboot from a wrap. Such cases re-anchor and flag uncertainty. ROS timestamps are estimates
    anchored to receipt, not clock synchronization.
    """

    def __init__(self, tick_us=100, timestamp_bytes=2):
        if tick_us <= 0 or timestamp_bytes not in (0, 1, 2, 4, 8):
            raise ValueError('Unsupported device timestamp format')
        self.tick_us = tick_us
        self.modulus = 1 << (timestamp_bytes * 8)
        self.last_raw = None
        self.offset_us = 0
        self.last_receipt = None
        self.anchor_ns = None
        self.last_sample_us = None

    def stamp(self, blocks, receipt, interval_us=None):
        """Return rows with device time, receipt time, estimated ROS time and quality."""
        if interval_us is not None and (not math.isfinite(interval_us) or interval_us <= 0):
            raise ValueError('Invalid FIFO sample period')
        uncertain = False
        clock_reset = False
        if self.last_receipt:
            elapsed = receipt.monotonic - self.last_receipt.monotonic
            ros_elapsed = (receipt.ros_ns - self.last_receipt.ros_ns) / 1e9
            if abs(ros_elapsed - elapsed) > 1.0 or elapsed < 0:
                self.anchor_ns = None
                clock_reset = True
            if elapsed * 1e6 >= self.modulus * self.tick_us:
                self.last_raw = None
                self.offset_us = 0
                self.last_sample_us = None
                self.anchor_ns = None
                uncertain = True
        polled = []
        for raw, rows, overflow in blocks:
            if raw is None:
                polled.append((None, rows, overflow))
                continue
            if self.last_raw is not None and raw < self.last_raw:
                if self.last_raw - raw > self.modulus // 2:
                    self.offset_us += self.modulus * self.tick_us
                else:
                    self.offset_us = 0
                    self.last_sample_us = None
                    self.anchor_ns = None
                    uncertain = True  # Reboot/reordering, not a guessed wrap.
            self.last_raw = raw
            polled.append((self.offset_us + raw * self.tick_us, rows, overflow))
        ticks = [t for t, _, _ in polled if t is not None]
        if ticks:
            candidate = receipt.ros_ns - int(ticks[-1] * 1000)
            # The smallest observed offset removes delivery-delay jitter. This
            # remains an estimate; it never implies synchronization with the MCU.
            self.anchor_ns = (
                candidate if self.anchor_ns is None else min(self.anchor_ns, candidate)
            )
        output = []
        for poll_us, rows, overflow in polled:
            if len(rows) > 1 and interval_us is None:
                raise ValueError('FIFO metadata has no sample period')
            for i, row in enumerate(rows):
                sample_us = (
                    None if poll_us is None else poll_us - (len(rows) - 1 - i) * (interval_us or 0)
                )
                quality = 'receipt_only' if poll_us is None else 'poll_estimated'
                if len(rows) > 1:
                    quality = 'fifo_estimated'
                if sample_us is not None and self.last_sample_us is not None:
                    if sample_us <= self.last_sample_us:
                        # Keep the actual estimated value instead of fabricating
                        # acquisition times to hide a backlog/rate mismatch.
                        quality = 'uncertain_overlap'
                if uncertain or overflow:
                    quality = 'uncertain_gap'
                if clock_reset:
                    quality = 'ros_clock_reset'
                stamp_ns = (
                    receipt.ros_ns if sample_us is None else int(self.anchor_ns + sample_us * 1000)
                )
                output.append(
                    {
                        'values': row,
                        'timestamp_us': sample_us,
                        'timestamp_ms': None if sample_us is None else sample_us / 1000,
                        'poll_timestamp_us': poll_us,
                        'stamp_ns': max(0, stamp_ns),
                        'receipt_ns': receipt.ros_ns,
                        'time_quality': quality,
                        'overflow': overflow,
                    }
                )
                self.last_sample_us = sample_us
        self.last_receipt = receipt
        return output
