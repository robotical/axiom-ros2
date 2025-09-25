Timestamps: decoders keep a 16‑bit unwrap counter; the bridge can later map ts_ms to header.stamp using a device↔host offset estimator. For now, we leave stamp unset or let the bridge stamp on publish.

VL53/VL6180 ranges/FOV: placeholder values; update with module‑specific data when available.

Validity bit (VL53L4CD): mirrors current firmware semantics ((~valid) & 0x04). If the device protocol changes, adjust here.

Topic naming: "{topic_key}_{addr}/{topic_suffix}" keeps multiple same‑type sensors unique.

Next: expand on multiple connection options