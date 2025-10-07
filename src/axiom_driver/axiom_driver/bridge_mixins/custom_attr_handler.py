from __future__ import annotations

from typing import Any, Dict, List


class CustomAttrHandler:
    """Decode attribute blocks handled via custom metadata."""

    def handle_attr(
        self,
        poll_resp_metadata: Dict[str, Any],
        payload: bytes,
    ) -> Dict[str, List[float]]:
        custom_meta = poll_resp_metadata.get('c')
        if not isinstance(custom_meta, dict):
            return {}

        custom_name = custom_meta.get('n')
        if not isinstance(custom_name, str) or not custom_name:
            return {}

        try:
            num_msg_bytes = int(poll_resp_metadata.get('b') or 0)
        except Exception:
            num_msg_bytes = 0
        if num_msg_bytes <= 0 or len(payload) < num_msg_bytes:
            return {}

        attr_defs = poll_resp_metadata.get('a') or []
        attr_values: Dict[str, List[float]] = {}
        for attr in attr_defs:
            name = attr.get('n') if isinstance(attr, dict) else None
            if isinstance(name, str) and name:
                attr_values[name] = []

        buf = memoryview(payload)[:num_msg_bytes]

        if custom_name == 'max30101_fifo':
            self._handle_max30101_fifo(buf, attr_values)
        elif custom_name == 'gravity_o2_calc':
            self._handle_gravity_o2_calc(buf, attr_values)

        return attr_values

    def _handle_max30101_fifo(
        self,
        buf: memoryview,
        attr_values: Dict[str, List[float]],
    ) -> None:
        if len(buf) < 3:
            return

        red_vec = attr_values.get('Red')
        ir_vec = attr_values.get('IR')
        if red_vec is None or ir_vec is None:
            return

        N = (buf[0] + 32 - buf[2]) % 32
        k = 3
        for _ in range(N):
            if k + 5 >= len(buf):
                break
            red_val = (buf[k] << 16) | (buf[k + 1] << 8) | buf[k + 2]
            ir_val = (buf[k + 3] << 16) | (buf[k + 4] << 8) | buf[k + 5]
            red_vec.append(int(red_val))
            ir_vec.append(int(ir_val))
            k += 6

    def _handle_gravity_o2_calc(
        self,
        buf: memoryview,
        attr_values: Dict[str, List[float]],
    ) -> None:
        if len(buf) < 3:
            return

        oxygen_vec = attr_values.get('oxygen')
        if oxygen_vec is None:
            return

        key = 20.9 / 120.0
        val = key * (buf[0] + (buf[1] / 10.0) + (buf[2] / 100.0))
        oxygen_vec.append(float(val))
