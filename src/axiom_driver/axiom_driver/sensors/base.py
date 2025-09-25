from abc import ABC, abstractmethod

class SensorDecoder(ABC):
    topic_key: str  # matches payload["_t"], e.g., "LSM6DS"

    def __init__(self, device_frame_id: str = "axiom_link"):
        self.frame_id = device_frame_id
    # Support unwrapping 16-bit device timestamps
        self._last_ts_wrapped = 0
        self._offset_ms = 0

    def unwrap_ts_ms(self, ts_wrapped: int) -> int:
        if ts_wrapped < self._last_ts_wrapped:
            self._offset_ms += 65536
        self._last_ts_wrapped = ts_wrapped
        return self._offset_ms + ts_wrapped

    @abstractmethod
    def decode_samples(self, hex_payload: str):
        """Yield (topic_suffix: str, ros_msg: object) for each decoded sample."""
        yield from ()
