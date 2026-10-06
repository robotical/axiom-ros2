"""Ordered metadata, decoding and device-time pipeline, owned by one worker."""

from collections import Counter
import math
import time
from urllib.parse import urlencode

from .commands import encode_command
from .custom import DecodeError
from .decoding import SampleDecoder
from .registry import DeviceRegistry, parse_devjson
from .timing import DeviceTimeline


class Pipeline:
    def __init__(
        self, request, on_sample, on_inventory=None, on_error=None, metadata_refresh_s=30.0
    ):
        self.request = request
        self.on_sample = on_sample
        self.on_inventory = on_inventory or (lambda devices: None)
        self.on_error = on_error or (lambda message: None)
        self.registry = DeviceRegistry()
        self.decoder = SampleDecoder()
        self.timelines = {}
        self.refresh_at = {}
        self.sample_periods = {}
        self.counts = Counter()
        self.metadata_refresh_s = metadata_refresh_s

    def reset(self):
        self.registry.reset()
        self.timelines.clear()
        self.refresh_at.clear()
        self.sample_periods.clear()
        self.on_inventory([])

    def clear_device(self, key):
        self.refresh_at.pop(key, None)
        for timeline_key in list(self.timelines):
            if timeline_key[0] == key:
                del self.timelines[timeline_key]

    def process(self, data, receipt, is_current=lambda: True):
        try:
            records = parse_devjson(data)
        except DecodeError as exc:
            self.error('invalid_envelope', exc)
            return
        for record in records:
            if not is_current():
                return
            try:
                device, changed = self.registry.observe(record, receipt.monotonic)
                if changed or record.online != 1:
                    self.clear_device(record.key)
                    self.sample_periods.pop(record.key, None)
                if device is None or not device.online:
                    continue
                if device.metadata and receipt.monotonic >= self.refresh_at.get(record.key, 0):
                    # Refresh per-instance metadata; installed profiles can change
                    # while keeping the same catalogue index and address.
                    self.refresh_at[record.key] = receipt.monotonic + 2.0
                    response = self.metadata(record)
                    if not is_current():
                        return
                    old = device.metadata
                    self.registry.install(record.key, device.revision, response)
                    if old != device.metadata:
                        self.registry.revision += 1
                        device.revision = self.registry.revision
                        self.clear_device(record.key)
                        self.sample_periods.pop(record.key, None)
                    self.refresh_at[record.key] = receipt.monotonic + self.metadata_refresh_s
                if not device.metadata:
                    self.registry.defer(device, record, receipt)
                    if receipt.monotonic < device.retry_at:
                        continue
                    device.retry_at = receipt.monotonic + 2.0
                    revision = device.revision
                    response = self.metadata(record)
                    if not is_current():
                        return
                    if not self.registry.install(record.key, revision, response):
                        continue
                    self.refresh_at[record.key] = receipt.monotonic + self.metadata_refresh_s
                    pending = self.registry.take_pending(device)
                else:
                    pending = [(record, receipt)]
                # Retire old interfaces before the first sample of a replacement.
                self.on_inventory(self.registry.snapshot(receipt.monotonic))
                for buffered_record, buffered_receipt in pending:
                    self.decode(device, buffered_record, buffered_receipt, is_current)
            except Exception as exc:
                self.error('device_errors', f'{record.key}: {exc}')
        if is_current():
            self.on_inventory(self.registry.snapshot(receipt.monotonic))

    def metadata(self, record):
        try:
            return self.request(record.key.metadata_path)
        except Exception as exc:
            # Only fall back for older firmware that lacks instance lookup.
            if not any(code in str(exc) for code in
                       ('failTypeMissing', 'API not found', 'failDeviceNotFound')):
                raise
            return self.request('devman/typeinfo?' + urlencode(
                {'bus': record.key.bus, 'type': str(record.type_ref)}))

    def decode(self, device, record, receipt, is_current):
        meta = device.metadata.get('resp')
        if not isinstance(meta, dict):
            return  # Output-only devices are discovered without measurements.
        for group, hex_data in record.groups.items():
            try:
                blocks = self.decoder.blocks(hex_data, meta, device.device_type)
                key = (device.key, group)
                if key not in self.timelines:
                    self.timelines[key] = DeviceTimeline(
                        int(meta.get('tr', meta.get('timestamp_resolution_us', 100))),
                        int(meta.get('tb', 2)),
                    )
                interval = self.sample_periods.get(device.key, meta.get('us'))
                samples = self.timelines[key].stamp(blocks, receipt, interval)
                self.counts['poll_blocks'] += len(blocks)
                self.counts['device_overflow'] += sum(b[2] for b in blocks)
                for sample in samples:
                    if not is_current():
                        return
                    self.on_sample(device, group, sample)
                    self.counts['samples'] += 1
                    if sample['time_quality'].startswith('uncertain'):
                        self.counts['uncertain_timestamps'] += 1
            except Exception as exc:
                self.error('decode_errors', f'{device.key} {group}: {exc}')

    def configure_rate(self, key, rate_hz):
        if not math.isfinite(rate_hz) or rate_hz <= 0:
            raise ValueError('Sample rate must be positive and finite')
        device = self.registry.devices.get(key)
        if device is None or not device.metadata or not device.online:
            raise ValueError('Device is not online with resolved metadata')
        actions = device.metadata.get('actions', [])
        supported = [a for a in actions if a.get('n') == '_conf.rate']
        rate = format(rate_hz, '.12g')
        if not supported or not any(rate in a.get('map', {}) for a in supported):
            raise ValueError('Sample rate is not in the device configuration map')
        path = 'devman/devconfig?' + urlencode(
            {'bus': key.bus, 'addr': '0x' + key.address, 'sampleRateHz': rate}
        )
        response = self.request(path)
        if not math.isclose(float(response.get('sampleRateHz', 0)), rate_hz, rel_tol=1e-6):
            raise ValueError('Firmware did not confirm the requested sample rate')
        self.sample_periods[key] = 1e6 / float(response['sampleRateHz'])
        self.clear_device(key)
        # Read back the effective polling configuration; request response contains
        # actual pollIntervalUs/numSamples, not a host-side estimate.
        return response

    def command(self, key, revision, action_name, values, stale_after):
        device = self.registry.devices.get(key)
        if (device is None or device.revision != revision or not device.online
                or time.monotonic() - device.last_seen > stale_after):
            raise ValueError('Device is offline, stale, or has been replaced')
        action = next((a for a in device.metadata.get('actions', [])
                       if a.get('n') == action_name), None)
        if action is None:
            raise ValueError('Command is no longer advertised by this device')
        if action_name == '_conf.rate':
            if len(values) != 1:
                raise ValueError('Expected one sample-rate argument in Hz')
            return self.configure_rate(key, values[0])
        result = None
        for operation in encode_command(action, values):
            if isinstance(operation, float):
                time.sleep(operation)
            else:
                result = self.request('devman/cmdraw?' + urlencode({
                    'deviceid': key.bus + '_' + key.address, 'hexWr': operation,
                }))
        return result

    def error(self, code, message):
        self.counts[code] += 1
        self.on_error(str(message))
