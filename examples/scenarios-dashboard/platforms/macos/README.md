# Optional Mac workstation adapter

Docker provides ROS Jazzy on Linux. USB WebSocket relays forward Axiom/Marty
firmware bytes; the ROS drivers own connection, acquisition and discovery.
noVNC streams the Linux desktop, containing Firefox and four tmux consoles.
The core drivers and visualization work directly on native Linux.

```bash
python3 -m venv .venv
.venv/bin/pip install pyserial websockets
.venv/bin/python platforms/macos/demo.py start --with-dashboard --marty-ip 192.168.1.8
```

Open http://127.0.0.1:6080/desktop.html. No driver or acquisition starts
with the workstation. The guide at http://127.0.0.1:8083 is optional.

For one Axiom, automatic USB selection works when exactly one board matches.
Use `--axiom-port /dev/cu.usbmodem2101` to select explicitly. For several boards:

```bash
.venv/bin/python platforms/macos/demo.py start --with-dashboard --marty-ip 192.168.1.8 \
  --axiom front=/dev/cu.usbmodem2101 --axiom rear=/dev/cu.usbmodem2201
```

Each board has a separate relay. The adapter writes `/ws/axioms.yaml` with
namespaces `axiom/front` and `axiom/rear` and exposes its path in
`AXIOM_ROS_BOARDS_FILE`. Start the multiple-driver command from the guide,
then connect and request acquisition separately for each board. A relay only
opens its USB connection when the ROS driver connects.

Stop/status/reset:

```bash
.venv/bin/python platforms/macos/demo.py status
.venv/bin/python platforms/macos/demo.py reset
.venv/bin/python platforms/macos/demo.py stop
```

Reset stops session commands and opens a clean guide and tmux session. Build and
project files remain. Console history is empty; commands are never replayed.
Closing the viewing browser leaves the Linux session running.

Terminal paste: Ctrl+Shift+V. The outer viewer also maps Command+V to Linux paste.
Mouse selection in tmux copies to the Linux clipboard through xclip; Shift+mouse
uses ordinary terminal selection. The viewer's clipboard panel can transfer text
between Mac and Linux when browser clipboard permissions require it.

The adapter owns only its labelled container, its reset controller and recorded
relay processes. Logs are in `.runtime` and inside the container under `/tmp`.
Native Linux does not use Docker, the relays, noVNC or the reset adapter.
