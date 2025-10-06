
from __future__ import annotations

import json

from ..ric_consts import (
    PROTO_RICREST,
    ELEM_CMDRESPJSON,
    TYPE_PUBLISH,
    PROTO_RAWCMDFRAME,
    PROTO_ROSSERIAL,
)

from ..bridge_mixins.sensor_payload_mixin import SensorPayloadMixin

class PublishMixin(SensorPayloadMixin):
    """Handling of publish frames arriving via dispatcher."""

    def _handle_publish_frame(self, frame: bytes):
        if len(frame) < 3:
            return
        msgnum, tprot = frame[0], frame[1]
        msg_type = (tprot >> 6) & 0x3
        proto = tprot & 0x3F

        # ROSSerial devjson publishes: payload is raw JSON (no element byte)
        if msg_type == TYPE_PUBLISH and proto == PROTO_ROSSERIAL:
            body = frame[2:]
            nul = body.find(b'\x00')
            if nul >= 0:
                body = body[:nul]
            try:
                obj = json.loads(body.decode('utf-8', errors='replace'))
                self.get_logger().debug(f"Publish payload: {json.dumps(obj, separators=(',', ':'))}")
                if isinstance(obj, dict):
                    self._dispatch_sensor_payload(obj)
            except Exception:
                self.get_logger().warn('Publish ROSSerial JSON decode failed')
            return

        # RAWCMDFRAME (RICJSON) publish → JSON (may be NUL-terminated)
        if msg_type == TYPE_PUBLISH and proto == PROTO_RAWCMDFRAME:
            body = frame[2:]
            nul = body.find(b'\x00')
            if nul >= 0:
                body = body[:nul]
            try:
                obj = json.loads(body.decode('utf-8', errors='replace'))
                if isinstance(obj, dict):
                    self._dispatch_sensor_payload(obj)
            except Exception:
                self.get_logger().warn('Publish RAWCMDFRAME JSON decode failed')
            return

        # Fallback: in case publish via RICREST/CMDRESPJSON
        if msg_type == TYPE_PUBLISH and proto == PROTO_RICREST and len(frame) >= 4:
            elem = frame[2]
            if elem == ELEM_CMDRESPJSON:
                body = frame[3:]
                nul = body.find(b'\x00')
                if nul >= 0:
                    body = body[:nul]
                try:
                    obj = json.loads(body.decode('utf-8', errors='replace'))
                    if isinstance(obj, dict):
                        self._dispatch_sensor_payload(obj)
                except Exception:
                    self.get_logger().warn('Publish RICREST JSON decode failed')
            return

        self.get_logger().warn(
            f'Unhandled publish/report frame: type={(tprot >> 6) & 0x3} proto={proto} len={len(frame)}'
        )
