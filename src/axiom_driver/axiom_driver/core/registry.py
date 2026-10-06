"""Versioned devjson records and device identities, owned by one pipeline worker."""

from collections import deque
import copy
from dataclasses import dataclass, field
from urllib.parse import urlencode

from .custom import DecodeError


def topic_token(value):
    """Encode names injectively into ROS tokens (including literal underscores)."""
    return ''.join(
        chr(b) if 48 <= b <= 57 or 65 <= b <= 90 or 97 <= b <= 122 else f'_{b:02x}'
        for b in str(value).encode('utf-8')
    )


@dataclass(frozen=True)
class DeviceKey:
    bus: str
    address: str

    @property
    def topic(self):
        return f'bus_{topic_token(self.bus)}/device_{topic_token(self.address)}'

    @property
    def metadata_path(self):
        # Bus zero identifies firmware-owned devices, not a registered bus.
        if self.bus == '0':
            return 'devman/typeinfo?' + urlencode({'deviceid': '0_' + self.address})
        return 'devman/typeinfo?' + urlencode({'bus': self.bus, 'addr': '0x' + self.address})


@dataclass
class DeviceRecord:
    key: DeviceKey
    type_ref: object
    online: int
    groups: dict


def parse_devjson(data):
    """Accept envelope v1 and explicitly supported legacy type-name records."""
    if not isinstance(data, dict):
        raise DecodeError('devjson must be an object')
    if '_v' in data and (type(data['_v']) is not int or data['_v'] != 1):
        raise DecodeError(f'Unsupported devjson envelope version: {data["_v"]!r}')
    records = []
    for bus, devices in data.items():
        if str(bus).startswith('_'):
            continue
        if not isinstance(devices, dict):
            continue  # REST replies can arrive on the same text channel.
        for address, packet in devices.items():
            if str(address).startswith('_'):
                continue
            if not isinstance(packet, dict):
                continue
            try:
                numeric_address = int(str(address), 16)
            except ValueError as exc:
                raise DecodeError(f'Invalid device address: {address!r}') from exc
            if numeric_address < 0 or numeric_address > 0xFFFFFFFF:
                raise DecodeError('Device address out of range')
            ref = packet.get('_i', packet.get('_t'))
            if not (
                (type(ref) is int and 0 <= ref <= 65535) or (isinstance(ref, str) and ref.strip())
            ):
                raise DecodeError('Device record has no valid type index/name')
            status = packet.get('_o', 1)
            if type(status) is not int or status not in (0, 1, 2):
                raise DecodeError('Unsupported device availability state')
            groups = {}
            for name, value in packet.items():
                if not name.startswith('_') and isinstance(value, str) and value:
                    groups[name] = value
            records.append(
                DeviceRecord(
                    DeviceKey(str(bus), format(numeric_address, 'x')), ref, status, groups
                )
            )
    return records


@dataclass
class Device:
    key: DeviceKey
    type_ref: object
    revision: int
    online: bool = True
    metadata: dict = field(default_factory=dict)
    name: str = ''
    role: str = 'normal'
    last_seen: float = 0.0
    retry_at: float = 0.0
    pending: deque = field(default_factory=deque)
    pending_bytes: int = 0
    dropped: int = 0

    @property
    def device_type(self):
        return self.metadata.get('type', str(self.type_ref))


class DeviceRegistry:
    """Session-scoped registry with bounded buffering during metadata lookup."""

    def __init__(self, max_devices=128, pending_bytes=65536):
        self.devices = {}
        self.max_devices = max_devices
        self.pending_limit = pending_bytes
        self.revision = 0

    def reset(self):
        self.devices.clear()
        self.revision += 1

    def observe(self, record, now):
        current = self.devices.get(record.key)
        if record.online == 2:
            self.devices.pop(record.key, None)
            return None, current is not None
        changed = current is None or current.type_ref != record.type_ref
        if changed:
            if current is None and len(self.devices) >= self.max_devices:
                raise DecodeError('Device registry capacity exceeded')
            self.revision += 1
            current = Device(record.key, record.type_ref, self.revision)
            self.devices[record.key] = current
        if not current.online and record.online == 1:
            # A hot-plug can change the installed profile without changing the
            # advertised type index. Always rediscover and reset its timeline.
            self.revision += 1
            current.revision = self.revision
            current.metadata = {}
            current.retry_at = 0.0
            changed = True
        current.online = bool(record.online)
        current.last_seen = now
        if not current.online:
            current.dropped += len(current.pending)
            current.pending.clear()
            current.pending_bytes = 0
        return current, changed

    def defer(self, device, record, receipt):
        size = max(1, sum(len(v) for v in record.groups.values()))
        if size > self.pending_limit:
            device.dropped += 1
            return
        while device.pending and (
            device.pending_bytes + size > self.pending_limit or len(device.pending) >= 64
        ):
            _, _, old_size = device.pending.popleft()
            device.pending_bytes -= old_size
            device.dropped += 1
        device.pending.append((record, receipt, size))
        device.pending_bytes += size

    def install(self, key, revision, response):
        device = self.devices.get(key)
        if device is None or device.revision != revision or not device.online:
            return False
        if response.get('rslt') not in ('ok', 'success', None):
            raise DecodeError(f'Metadata lookup failed: {response.get("rslt")}')
        info = response.get('devinfo') or response.get('deviceTypeInfo') or response.get('info')
        if not isinstance(info, dict) or not (
            isinstance(info.get('resp'), dict)
            or info.get('resp') is None or info.get('resp') is False
        ):
            raise DecodeError('Device metadata has an invalid response schema')
        if not isinstance(info.get('type'), str) or not info['type']:
            raise DecodeError('Device metadata has no type name')
        index = response.get('dtIdx')
        if isinstance(device.type_ref, int) and index is not None and index != device.type_ref:
            raise DecodeError('Device type changed during metadata lookup')
        device.metadata = copy.deepcopy(info)
        device.name = str(response.get('name', ''))
        device.role = str(response.get('role', 'normal'))
        return True

    def take_pending(self, device):
        pending = [(record, receipt) for record, receipt, _ in device.pending]
        device.pending.clear()
        device.pending_bytes = 0
        return pending

    def invalidate(self, key):
        device = self.devices.get(key)
        if device:
            self.revision += 1
            device.revision = self.revision
            device.metadata = {}
            device.retry_at = 0.0
            device.dropped += len(device.pending)
            device.pending.clear()
            device.pending_bytes = 0

    def snapshot(self, now, stale_after=5.0):
        return [
            {
                'bus': d.key.bus,
                'address': d.key.address,
                'type': d.device_type,
                'type_ref': d.type_ref,
                'revision': d.revision,
                'name': d.name,
                'role': d.role,
                'online': d.online,
                'stale': now - d.last_seen > stale_after,
                'metadata_ready': bool(d.metadata),
                'topic': d.key.topic,
                'age_s': max(0.0, now - d.last_seen),
                'dropped_pending': d.dropped,
            }
            for d in self.devices.values()
        ]
