# Firmware contract and migration

## Inspected baseline

| Source | Revision |
|---|---|
| ROS before this change | `06561e0` |
| RoboticalAxiom1 catalogue | `0941576` |
| RaftCore | `9594620` |
| RaftI2C | `1f2eeef` |
| RaftSysMods local checkout | `a1af7f1` |

The Axiom configuration pins RaftSysMods `88512b7`; that object was not available
locally. These tests establish alignment with the inspected source, not proof of
the exact firmware flashed on a board. The runtime `v` handshake is included in
`device_metadata`. Catalogue fixtures retain source paths, revision and SHA256.

## Wire contract

Use one `/ws` connection with RICSerial framing for both RPC and devjson. Current
RaftCore's RAWCMDFRAME `/devjson` route executes commands but does not transmit API
responses. The bridge normalizes a `/devjson` URI to `/ws`; it does not claim an
unacknowledged command succeeded. Raw RICJSON, devbin and bridged-RIC device envelopes
are not implemented; unsupported traffic produces diagnostics.

Mini-HDLC uses firmware's `0xe7` flag, `0xd7` escape, XOR `0x20`, and CRC16-CCITT.
Serial OverAscii separates high-bit protocol bytes from low-bit console text,
including fragmented/interleaved reads. `auto` sends OverAscii immediately (current
firmware), rather than probing using uncorrelated ASCII commands. Explicit `ascii`
mode serializes requests and closes the session after a failed request because late
unnumbered replies cannot safely be correlated. Numbered RPCs have bounded IDs,
timeouts, quarantine of expired IDs, cancellation and generation checks.

Version 1 publication shape:

```json
{"_t":0,"_v":1,"1":{"38":{"_i":4,"_o":1,"x":"006400..."}}}
```

The outer `_t` is the publication topic index. Device `_i` is a catalogue type
index; legacy device `_t` type names are also accepted. `_o` is 0 offline, 1 online,
2 removed. Metadata is fetched per instance with
`devman/typeinfo?bus=1&addr=0x38`; a narrowly scoped legacy type lookup handles older
API failures. Devices retain first packets during discovery, within bounded storage.
Hot-plug, type changes, removal, reconnect and periodic refresh invalidate metadata
and clocks. Removed-device publishers are destroyed.

## Decoding

Ordinary profiles use the advertised byte layout, signed fields, bit operations,
scaling, LUT and validity rules. Output storage types never truncate fractional
engineering values. Pixel arrays stay vectors; FIFO rows become separate samples.
Fixed padded devjson blocks are decoded at `.b + timestamp bytes`, without guessing
sample boundaries from zeros. Default timestamps are 2-byte BE ticks of 100 µs.

Six custom contracts have native, bounded implementations: `lsm6ds_fifo`, `vcp_fifo`,
`max30101_fifo`, `gravity_o2_calc`, `ltr329_light_calc`, `scd40_calc`. Their firmware
metadata hashes are allowlisted. Remote C/JavaScript is never executed. Unknown or
changed custom definitions fail visibly; adding support requires a reviewed native
handler and fixture update. LSM alignment/signed values, VCP mode/count bounds and
MAX fixed read capacity/overflow are covered by synthetic source-derived vectors.

SCD40 is an explicit correction to the inspected catalogue's malformed C decoder:
three big-endian words with CRC8 are decoded using Sensirion's conversions, without
double scaling. See [Sensirion's API](https://sensirion.github.io/python-i2c-scd4x/api.html).
This driver correction does not repair other clients consuming that catalogue code.
AMG8833 negative 12-bit temperature values also retain their sign after shifting.

## Migrating existing clients

- Replace type/address-derived names (for example `LSM6DS_76a/...`) with inventory
  `topic` prefixes such as `bus_1/device_76a/...`. Addresses remain hexadecimal.
- Replace separate WS data/control sockets with the single framed `/ws` session.
- Replace `serial.autosub` / `serial.devjson_rate_hz` with `autosub` /
  `publish_rate_hz`. `ricrest_proto` and configurable HDLC delimiters were removed;
  direct current-firmware framing is explicit.
- `ws_pcol` supports `RICSerial` and `RICFrame` only; RICFrame requires a matching
  firmware endpoint. Current Axiom `/ws` uses RICSerial.
- Subscribe with BEST_EFFORT QoS unless configured otherwise. Discovery/metadata are
  reliable and transient local. Configure measured sensor frames and external TF.
- Generic measurements now include raw/value/unit/SI/valid fields. Consumers must
  respect validity and null/NaN, and must not treat receipt time as acquisition time.
- Change hardware sample rates through `set_sample_rate`; publication rate controls
  delivery batching and is independent of sensor ODR.
- Removed mixins, Dispatcher and placeholder sensor classes are internal API changes.
  Use `core.Session`, `core.Pipeline` and the ROS interfaces.

## Remaining firmware and product boundaries

StatePublisher consumers drain the same device polling queue. One upstream bridge
plus DDS fan-out avoids multiple ROS clients draining it, but external firmware
clients can still interfere. Fixing multicast needs a firmware queue/reader design.
No sequence counter is supplied, so exact missing-sample counts cannot be proven;
local drops, native overflow and uncertain timestamps are observable.

This is a sensor bridge with observed servo state and explicit REST access. It is
not a ros2_control hardware interface, actuator arbitration layer, robot description,
calibration suite or sensor-fusion stack. These are separate features requiring a
robot-specific control and safety design.
