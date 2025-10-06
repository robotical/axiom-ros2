"""Legacy decoder registry (retained for backwards compatibility).

Firmware-provided metadata now drives decoding dynamically inside
``SensorPayloadMixin``. These helpers exist so any old imports continue to
resolve, but they always return ``None``.
"""

from typing import Optional


def get_decoder_by_identifier(identifier: str, frame_id: str):  # noqa: D401
    """Return ``None``; dynamic firmware decoders supersede this helper."""
    return None


def get_decoder(topic_key: str, frame_id: str):  # noqa: D401
    """Return ``None``; preserved for compatibility with legacy code."""
    return None
