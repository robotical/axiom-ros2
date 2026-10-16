# tmux consoles for Axiom ROS 2

Complete the [build and local configuration](../README.md) first. From a normal
Bash terminal outside an attached tmux session, at the repository root:

```bash
sudo apt install tmux
bash scripts/ros_tmux.sh
```

The helper creates four empty panes labelled **Terminal 1–4**, or attaches its
existing ROS session. Use the labels to follow a walkthrough; screen positions
can change as the window is resized. Start discovery in Terminal 1; it connects and acquires automatically.

Each new pane loads the machine settings, configured ROS installation and built
workspace through `scripts/setup_env.sh`. It starts at `ROS_WORKSPACE`, which
defaults to the checkout. If you configured a separate workspace, change to the
repository root before using relative `scripts/...` paths.

| Pane | Basic session | Thermal RViz | Foxglove |
|---|---|---|---|
| Terminal 1 | Host driver | Host driver | Host driver |
| Terminal 2 | Services and measurement checks | Services and grid inspection | Services and image inspection |
| Terminal 3 | Viewer or additional checks | Heatmap visualiser | Foxglove bridge |
| Terminal 4 | Additional checks or unused | RViz | Optional rate checks |

The browser or desktop Foxglove viewer runs separately. The optional scenarios
dashboard can use an extra outer terminal if all four panes are occupied.

## Controls

For a tmux shortcut, press **Ctrl+b**, release both keys, then press the listed
key. Use lowercase d and z.

| Action | Keys |
|---|---|
| Switch panes | Ctrl+b, then an arrow; mouse clicks also work |
| Zoom the selected pane | Ctrl+b, then z; repeat to restore the layout |
| Detach to the outer terminal | Ctrl+b, then d |
| Enter scrollback | Ctrl+b, then [; use arrows/Page Up; q exits |
| Paste the tmux copy buffer | Ctrl+b, then ] |
| Interrupt the selected foreground command | Ctrl+C |

Detach keeps commands running. To return, run `bash scripts/ros_tmux.sh` again
from the repository root. It uses the dedicated `axiom-ros` tmux socket and
`axiom` session, so use this helper for reattaching rather than a bare `tmux attach`.
After a host reboot, restart the helper and the ROS commands.

## Copy and paste

In the Ubuntu desktop terminal, hold Shift while dragging to use the terminal's
selection, then Ctrl+Shift+C to copy and Ctrl+Shift+V to paste. The right-click
menu also works. Zooming a pane first makes long output easier to select.
Ctrl+C interrupts a process; use the copy shortcut for selected output.

For automatic mouse-drag copying to an **X11 desktop clipboard**, the helper
supports `xclip`. Install it in a desktop terminal on the host:

```bash
sudo apt install xclip
```

If the session is already open, reload its configuration from the repository root:

```bash
tmux -L axiom-ros source-file scripts/tmux.conf
```

The helper's default copy-mode binding pipes mouse selections to `xclip`. It needs
a desktop display; a plain SSH terminal needs its own clipboard workflow. Remote
desktop clipboard sharing also depends on the client. The desktop clipboard and
tmux copy buffer are separate.

## Refresh or finish a session

Reattaching preserves existing shells and commands. After rebuilding or changing
`config/machine.env`, stop affected ROS processes and reload each reused pane:

```bash
source scripts/setup_env.sh
```

Restart those processes with the refreshed settings. All ROS terminals need the
same domain and compatible middleware settings. Before finishing, use the driver's
stop-acquisition and disconnect services while it is still running, then stop the
remaining foreground processes. Detach alone does not perform cleanup.

See the [published tmux guide](https://userguides.robotical.io/axiom/ros2/getting_started#use_tmux_for_the_ros_consoles)
and [official tmux introduction](https://github.com/tmux/tmux/wiki/Getting-Started).
