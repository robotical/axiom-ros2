# Minimal RIC Serial Subscriber

This script connects to the device over a serial/USB console port and subscribes to a publish topic (e.g. `devjson`). In binary mode (default) it properly encodes a RICREST subscription command using RICSerial + MiniHDLC + ProtocolOverAscii and decodes incoming publish frames continuously.

## Features
- Binary subscription (default) with full frame decoding
- Optional legacy ASCII mode (`--ascii`)
- Automatic keep-alive / re-subscription (`--keepalive-secs`)
- Adjustable publish rate and topic name
- Debug flag for verbose frame diagnostics

## Install
```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run (Binary Mode)
```bash
python minimalserialconnection.py --port /dev/tty.usbmodemXXXX --name devjson --rate 2
```

## Run (ASCII Mode)
```bash
python minimalserialconnection.py --port /dev/tty.usbmodemXXXX --name devjson --rate 2 --ascii
```

## Useful Flags
- `--port` Serial device path.
- `--baud` Baud rate (ignored by USB Serial/JTAG firmware but required by host lib).
- `--name` Topic / subscription name (e.g. `devjson`, `Status`).
- `--rate` Publish rate Hz (0 disables).
- `--ascii` Use simple ASCII request/line reader (no binary decoding).
- `--keepalive-secs` Periodic re-send of subscription (0 disables).
- `--debug` Verbose logging of frames and ASCII lines.

## Troubleshooting
| Symptom | Fix |
|---------|-----|
| No publishes printing | Ensure correct `--name` and `--rate > 0`; stay in binary mode. |
| High-bit gibberish in ASCII mode | You're seeing binary frames; omit `--ascii`. |
| Intermittent missing frames | Lower rate; check cable quality; leave debug on to inspect CRC acceptance. |
| Immediate port open error | Check your device path and permissions (`ls /dev/tty.*`). |

## Notes
- Response frames (command acknowledgements) are printed with `[RESP]` prefix.
- Publish frames (msgType=2 proto=0) print with `[PUB]` prefix and payload JSON.
- The script keeps a rolling message counter (0-255) for commands.

## License
MIT (adjust as needed).
