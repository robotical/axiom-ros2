from .lsm6ds import LSM6DSDecoder
from .vl53l4cd import VL53L4CDDecoder
from .vl6180 import VL6180Decoder
from .aht20 import AHT20Decoder

_DECODERS = {c.topic_key: c for c in [LSM6DSDecoder, VL53L4CDDecoder, VL6180Decoder, AHT20Decoder]}

def get_decoder(topic_key: str, frame_id: str):
    cls = _DECODERS.get(topic_key)
    return cls(frame_id) if cls else None