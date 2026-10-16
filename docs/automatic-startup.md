# Automatic Axiom startup

Use the host firmware variant and build the driver as described in the
[README](../README.md). No Zenoh router is needed for the normal DDS host driver.

```bash
source scripts/setup_env.sh
ros2 launch axiom_driver axiom.launch.py
```

No board file, USB path or IP address is required. Discovery waits quietly when
no Axiom is present. It checks Espressif USB candidates and the HTTP mDNS services
advertised by Axiom firmware, verifies each board, then starts connection and
sensor acquisition automatically. Connect and power Wi-Fi Axioms on the same
multicast-capable local network as the host first. Discovery does not provision
Wi-Fi credentials or scan IP subnets.

## Find your board namespace

```bash
ros2 topic echo /axiom_discovery/boards --qos-durability transient_local --once
ros2 topic list -t --no-daemon
```

The retained JSON inventory gives each board's firmware MAC `id`, namespace,
transport, endpoint and connection state. Unconfigured boards use
`/axiom_<12-digit-MAC>`, for example `/axiom_001122334455`. The entire firmware MAC
is used, so naming does not depend on discovery order or `/dev/ttyACM` numbering.
The frame prefix is derived from that namespace. Sensor topics and their units
retain their existing contracts.

One bridge runs per board. USB is preferred when both USB and Wi-Fi are verified;
a later USB connection replaces a Wi-Fi bridge under the same namespace. If USB
disappears and a verified Wi-Fi endpoint is available, discovery falls back to
Wi-Fi. Other boards keep running. A reappearing endpoint is verified again.
An endpoint presenting a different board is re-identified before acquisition.

Automatic identity requires a valid firmware `MAC` field. Recognition still
checks successful `rslt` and an Axiom `SystemName`. Older firmware without a MAC
can use an explicitly configured bridge launch, but cannot participate in
identity-based automatic discovery.

## Optional names, aliases and board selection

Create a board file only when you want overrides. This extends the existing
`axioms` mapping; existing explicit endpoint entries also work. Save it anywhere
and pass `boards_file:=/absolute/path/boards.yaml`, or select it through
`AXIOM_ROS_BOARDS_FILE` in `config/machine.env`.

Replace the example IDs with IDs from your inventory:

```yaml
discovery:
  usb: true
  wifi: true
  include_unconfigured: false
axioms:
  robot/front:
    id: '001122334455'
    publish_rate_hz: 20.0
    topic_aliases:
      imu/data_raw: {type: LSM6DS, source: imu/data_raw}
      range: {type: VL53L4CD, source: range}
  robot/rear:
    id: 'aabbccddeeff'
```

```bash
ros2 launch axiom_driver axiom.launch.py boards_file:=/absolute/path/boards.yaml
```

This produces `/robot/front` and `/robot/rear`. `include_unconfigured: false`
allows only matching board entries to acquire. Use it on a shared lab network or
when several robots share the same LAN. With the default `true`, all verified
Axioms visible to the host are eligible. Discovery may read version information
from candidates before it knows whether their IDs are selected.

Board namespace and robot membership are host configuration. `ROS_DOMAIN_ID`
controls which ROS processes communicate; it does not select physical Axioms.
Give each robot's processes a suitable domain and use board IDs to select that
robot's hardware. All boards managed by one discovery process share its ROS domain.

Set `transport: serial` or `transport: ws` in an identity entry to restrict its
transport. For networks where multicast is unavailable, use a configured endpoint:

```yaml
axioms:
  axiom:
    transport: ws
    device_uri: ws://192.0.2.10/ws
```

Replace the illustrative IP with the board's reachable address. Endpoints use the
same verification and identity deduplication as discovered boards. Avoid multiple
entries for one board; ambiguous matches are reported and are not started.
Namespaces, frame prefixes, configured IDs and configured endpoints must be unique.
Restart discovery after editing its startup configuration.

## Manual control and recovery

Connection, reconnection and acquisition default to enabled. To start a selected
board disconnected with acquisition off, set these values on its board entry:

```yaml
    auto_connect: false
    auto_reconnect: false
    autosub: false
```

The bridge services remain available. Replace `/axiom` below with your board's
actual namespace:

```bash
ros2 service call /axiom/connect axiom_interfaces/srv/Connect '{device_uri: ""}'
ros2 service call /axiom/publish_data_subscription \
  axiom_interfaces/srv/PublishedDataSubscription '{rate_hz: 20.0}'
```

An intentional disconnect disables automatic reconnect. Stopping acquisition with
rate zero leaves the connection open. These choices are retained by discovery over
transport changes and reappearance during the same discovery process. Restarting
discovery reapplies startup configuration. A normal unexpected connection failure
retries according to `auto_reconnect`; failed verification retries after five
seconds on the next scan. Scanning runs every two seconds.

`axiom_minimal_launch.py` and `multi_axiom.launch.py` remain available for explicitly
configured endpoints and parameter-file/CLI overrides. They now use automatic
startup defaults too; pass all three flags as false for a manual single-board
launch. The compatibility `axiom_usb_discovery` executable runs USB discovery only.
The normal `axiom_discovery` executable includes both USB and Wi-Fi.

## Ownership and shutdown

Run one acquisition owner per physical board. Current host-driver sessions take
nonblocking per-user endpoint and board locks on the same computer. A competing
session reports that the board is owned and retries; its port is not read alongside
the owning driver. Locks are released on close or process exit. These advisory locks
do not coordinate different computers, older driver versions, browsers or native
Zenoh routers. Close an updater, monitor or other acquisition client first.

Stop viewers and discovery with Ctrl+C when finished. Discovery destroys its
bridges, closes their transports and releases worker threads. Closing an echo or
detaching tmux alone leaves discovery running.
