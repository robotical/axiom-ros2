# Optional Mac workstation adapter

Docker provides ROS Jazzy on Linux. USB WebSocket relays forward Axiom/Marty
firmware bytes; the ROS drivers own connection, acquisition and discovery.
noVNC streams the Linux desktop, containing Firefox and four tmux consoles.
The core drivers and visualisation work directly on native Linux; see the
[host setup](../../../../README.md) and [user guides](https://userguides.robotical.io/axiom/ros2/start).
This optional adapter supplies a Linux GUI on macOS and is separate from that
native workflow. Use host firmware and stop any other acquisition client connected
to the same physical Axiom.

From the repository root, change to this example's directory before the commands
below:

```bash
cd examples/scenarios-dashboard
```

```bash
python3 -m venv .venv
.venv/bin/pip install pyserial websockets
.venv/bin/python platforms/macos/demo.py start --with-dashboard
```

Open http://127.0.0.1:6080/desktop.html. No driver or acquisition starts
with the workstation. The guide at http://127.0.0.1:8083 is optional.

For one Axiom, automatic USB selection works when exactly one board matches.
Use `--axiom-port /dev/cu.usbmodemREPLACE_WITH_AXIOM_DEVICE` to select the actual
macOS USB path explicitly. For several boards, replace both placeholders with
different physical devices:

```bash
.venv/bin/python platforms/macos/demo.py start --with-dashboard \
  --axiom front=/dev/cu.usbmodemREPLACE_WITH_FRONT --axiom rear=/dev/cu.usbmodemREPLACE_WITH_REAR
```

Each board has a separate relay. The adapter writes `/ws/axioms.yaml` with
namespaces `axiom/front` and `axiom/rear` and exposes its path in
`AXIOM_ROS_BOARDS_FILE`. Start the multiple-driver command from the guide,
then connect and request acquisition separately for each board. A relay only
opens its USB connection when the ROS driver connects.

For an optional Marty Wi-Fi connection, add `--marty-ip MARTY_IP` with its
actual address. Marty scenarios need its packages/hardware; Axiom-only scenarios
do not need a Marty connection.

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
