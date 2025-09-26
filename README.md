
## Protocols, Framing, Encoding & Transports

This driver layers several light protocols to move RIC (Robot Interface Controller) frames between the device and ROS 2.

### Layer Overview (outer → inner)

1. Physical / Transport  
   - Serial: [`axiom_driver.transports.serial.SerialTransport`](src/axiom_driver/axiom_driver/transports/serial.py)  
   - WebSocket (data + control): implemented in mixin [`axiom_driver.bridge_mixins.WebSocketMixin`](src/axiom_driver/axiom_driver/bridge_mixins.py)  
2. Optional ASCII-safe wrapper (serial only when using OverAscii)  
   - ProtocolOverAscii: encoder [`axiom_driver.protocols.overascii.encode`](src/axiom_driver/axiom_driver/protocols/overascii.py), streaming decoder [`axiom_driver.protocols.overascii.Decoder`](src/axiom_driver/axiom_driver/protocols/overascii.py)  
3. Mini-HDLC (framing + CRC16)  
   - [`axiom_driver.mini_hdlc.MiniHDLC`](src/axiom_driver/axiom_driver/mini_hdlc.py) (methods: `encode()`, `try_decode()`)  
4. Inner RIC frame (header + payload)  
   - [`axiom_driver.protocols.ric_frame.RICFrame`](src/axiom_driver/axiom_driver/protocols/ric_frame.py)  
     Format: `[msgNum:1][type/proto:1][elem:1][payload...]`  
5. Dispacher / RPC correlation  
   - [`axiom_driver.protocols.dispatcher.Dispatcher`](src/axiom_driver/axiom_driver/protocols/dispatcher.py) matches responses (CMDRESPJSON) by `msgNum`  
6. Sensor payload JSON (devjson) → decoded into ROS messages  
   - [`axiom_driver.bridge_mixins.SensorPayloadMixin`](src/axiom_driver/axiom_driver/bridge_mixins.py)  
   - Decoders:  
     - IMU: [`axiom_driver.sensors.lsm6ds.LSM6DSDecoder`](src/axiom_driver/axiom_driver/sensors/lsm6ds.py)  
     - Ranges: [`axiom_driver.sensors.vl53l4cd.VL53L4CDDecoder`](src/axiom_driver/axiom_driver/sensors/vl53l4cd.py), [`axiom_driver.sensors.vl6180.VL6180Decoder`](src/axiom_driver/axiom_driver/sensors/vl6180.py)  
     - Environment: [`axiom_driver.sensors.aht20.AHT20Decoder`](src/axiom_driver/axiom_driver/sensors/aht20.py)  
   - Registry: [`axiom_driver.sensors.registry.get_decoder`](src/axiom_driver/axiom_driver/sensors/registry.py)

### Message Type & Protocol IDs

Defined in [`axiom_driver.ric_consts`](src/axiom_driver/axiom_driver/ric_consts.py):

- Types: `TYPE_COMMAND`, `TYPE_RESPONSE`, `TYPE_PUBLISH`
- Protocols: `PROTO_ROSSERIAL` (devjson publish), `PROTO_RICREST`, `PROTO_BRIDGE_RICREST`, `PROTO_RAWCMDFRAME`
- Elements: `ELEM_URL`, `ELEM_CMDRESPJSON`, etc.
- Helper: [`axiom_driver.ric_consts.pack_type_proto`](src/axiom_driver/axiom_driver/ric_consts.py)

### WebSocket Modes

Parameter `ws_pcol` (see [`axiom_driver.axiom_bridge_node.AxiomBridgeNode._ws_mode`](src/axiom_driver/axiom_driver/axiom_bridge_node.py)):

- `RICSerial`: Binary WS frames carry Mini-HDLC wrapped RIC frames
- `RICFrame`: Binary WS frames carry raw RIC frames (no HDLC)
- `RICJSON`: (future) plain JSON semantics

Control channel receive path: [`axiom_driver.bridge_mixins.WebSocketMixin._on_message_ctrl`](src/axiom_driver/axiom_driver/bridge_mixins.py)

### Serial Modes

Parameter `serial.mode` (auto-detected in [`axiom_driver.bridge_mixins.SerialMixin._serial_on_bytes`](src/axiom_driver/axiom_driver/bridge_mixins.py)):

- `ascii`: Lines of console text; JSON responses/publishes extracted in `_feed_console`
- `overascii`: ProtocolOverAscii → Mini-HDLC → RIC frame
- `auto`: Start ASCII, switch to OverAscii on high-bit / sentinel patterns

OverAscii streaming decoder: [`axiom_driver.protocols.overascii.Decoder.feed`](src/axiom_driver/axiom_driver/protocols/overascii.py) → feeds HDLC deframer.

### Framing & CRC

Mini-HDLC: [`axiom_driver.mini_hdlc.MiniHDLC`](src/axiom_driver/axiom_driver/mini_hdlc.py)  
- Flag (default 0x7E), Escape (0x7D), XOR (0x20) can be overridden via parameters `hdlc_flag`, `hdlc_escape`, `hdlc_xor` (declared in [`axiom_driver.axiom_bridge_node`](src/axiom_driver/axiom_driver/axiom_bridge_node.py)).  
- CRC: `crc16_ccitt()` table-driven implementation (same file).

Serial deframing (streaming): [`axiom_driver.protocols.ric_serial.RICSerial.feed_bytes`](src/axiom_driver/axiom_driver/protocols/ric_serial.py)  
Single-shot decode (WebSocket control path): [`axiom_driver.mini_hdlc.MiniHDLC.try_decode`](src/axiom_driver/axiom_driver/mini_hdlc.py)

### RPC Flow (RIC REST URL)

Service handler: [`axiom_driver.axiom_bridge_node.AxiomBridgeNode.handle_ric_rest_url`](src/axiom_driver/axiom_driver/axiom_bridge_node.py)

Steps (serial OverAscii path):
1. Pack inner frame: [`axiom_driver.protocols.ric_frame.RICFrame.pack`](src/axiom_driver/axiom_driver/protocols/ric_frame.py)
2. Wrap HDLC: [`axiom_driver.protocols.ric_serial.RICSerial.encode`](src/axiom_driver/axiom_driver/protocols/ric_serial.py)
3. OverAscii encode: [`axiom_driver.protocols.overascii.encode`](src/axiom_driver/axiom_driver/protocols/overascii.py)
4. Send via [`axiom_driver.transports.serial.SerialTransport.send`](src/axiom_driver/axiom_driver/transports/serial.py)
5. Response matched by [`axiom_driver.protocols.dispatcher.Dispatcher`](src/axiom_driver/axiom_driver/protocols/dispatcher.py)

WS RICSerial path skips OverAscii (HDLC only). WS RICFrame path skips both OverAscii + HDLC.

### Publish (Sensor Data) Flow

1. Device emits devjson:
   - Serial ASCII: parsed in [`axiom_driver.bridge_mixins.SerialMixin._feed_console`](src/axiom_driver/axiom_driver/bridge_mixins.py)
   - Serial OverAscii / WS: RIC publish frame handled in [`axiom_driver.bridge_mixins.PublishMixin._handle_publish_frame`](src/axiom_driver/axiom_driver/bridge_mixins.py) or serial frame handler.
2. Payload dict dispatched via [`axiom_driver.bridge_mixins.SensorPayloadMixin._dispatch_sensor_payload`](src/axiom_driver/axiom_driver/bridge_mixins.py)
3. Decoder converts hex sample stream → ROS messages (e.g. [`axiom_driver.sensors.lsm6ds.LSM6DSDecoder.decode_samples`](src/axiom_driver/axiom_driver/sensors/lsm6ds.py))
4. Publishers cached by [`axiom_driver.publisher_cache.PublisherCache`](src/axiom_driver/axiom_driver/publisher_cache.py)

### Encoding / Decoding Examples

RIC URL command (WS, RICSerial):

```python
from axiom_driver.protocols.ric_frame import RICFrame
from axiom_driver.ric_consts import TYPE_COMMAND, PROTO_RICREST, ELEM_URL, pack_type_proto
# Given msgnum, url_str, and MiniHDLC instance hdlc
ric = RICFrame.pack(msgnum, pack_type_proto(TYPE_COMMAND, PROTO_RICREST), ELEM_URL, url_str.encode())
payload = hdlc.encode(ric)  # send as binary WS frame
```

OverAscii wrap (serial):

```python
from axiom_driver.protocols.overascii import encode as oa_encode
hdlc_bytes = ric_serial.encode(ric_frame_bytes)
ascii_safe = oa_encode(hdlc_bytes)
serial_transport.send(ascii_safe)
```

Mini-HDLC single frame decode:

```python
ok, inner = mini_hdlc.try_decode(framed_bytes)
if ok:
    # inner is RIC frame
    ...
```

Streaming serial deframe (inside reader loop):

```python
ric_serial.feed_bytes(raw_chunk)  # internally accumulates, finds flags, CRC checks, invokes on_frame
```

### Error / Timeout Handling

- WS control RPC timeout: logged in [`axiom_driver.axiom_bridge_node.AxiomBridgeNode.handle_ric_rest_url`](src/axiom_driver/axiom_driver/axiom_bridge_node.py)
- Serial HDLC decode errors surfaced via `on_error` callback in [`axiom_driver.protocols.ric_serial.RICSerial`](src/axiom_driver/axiom_driver/protocols/ric_serial.py)
- Dispatcher reset on disconnect: [`axiom_driver.protocols.dispatcher.Dispatcher.reset_waiters`](src/axiom_driver/axiom_driver/protocols/dispatcher.py)

### Parameter Hooks (selected)

Declared in [`axiom_driver.axiom_bridge_node.AxiomBridgeNode.__init__`](src/axiom_driver/axiom_driver/axiom_bridge_node.py):
- `ws_pcol` (RICSerial|RICFrame|RICJSON)
- `hdlc_flag`, `hdlc_escape`, `hdlc_xor`
- `serial.mode` (auto/ascii/overascii)
- `serial.autosub`, `serial.devjson_rate_hz`
- `ricrest_proto` (RICREST|BRIDGE_RICREST)
- `rpc_default_timeout`

### Extending

Add a new sensor decoder:
1. Implement subclass of [`axiom_driver.sensors.base.SensorDecoder`](src/axiom_driver/axiom_driver/sensors/base.py)
2. Add to `_DECODERS` in [`axiom_driver.sensors.registry`](src/axiom_driver/axiom_driver/sensors/registry.py)

Add a new framing / protocol layer:
- Wrap before Mini-HDLC (outer) or replace Mini-HDLC with alternate deframer, then adapt the receive path in `SerialMixin` / `WebSocketMixin`.

### Quick Reference

| Concern        | Component |
| -------------- | --------- |
| ASCII-safe tunnel | OverAscii (`encode()`, `Decoder.feed()`) |
| Framing + CRC  | Mini-HDLC (`MiniHDLC.encode`, `.try_decode`) |
| Inner frame    | RICFrame (`RICFrame.pack`) |
| RPC matching   | Dispatcher (`Dispatcher.register_waiter`, `.handle_frame`) |
| Serial stream  | RICSerial (`feed_bytes`) |
| Sensor decode  | Sensor decoders in `sensors/` |
| Dynamic pubs   | `PublisherCache` |

