"""ROS message contracts layered over decoded firmware samples."""

import json
import math

from axiom_interfaces.msg import AxiomPowerState, DeviceSample, Imu6, ThermalGrid, VL53L4CDReading
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from sensor_msgs.msg import (
    BatteryState, Image, Imu, JointState, Range, RelativeHumidity, Temperature,
)
from std_msgs.msg import String

from .core.aliases import bindings
from .core.grids import float32_image_data, zone_grid
from .core.topic_names import image_suffix, measurement_topic, sensor_topic
from .publisher_cache import PublisherCache


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {k: json_safe(v) for k, v in value.items() if k != 'meta'}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    return value


def json_text(value):
    return json.dumps(json_safe(value), allow_nan=False, separators=(',', ':'))


class RosAdapters:
    def __init__(
        self,
        node,
        qos,
        frame_prefix='axiom',
        sensor_frames=None,
        custom_messages=True,
        range_fov=0.0,
        qos_overrides=None,
        topic_aliases=None,
    ):
        self.cache = PublisherCache(node, qos)
        self.qos_overrides = {
            topic: QoSProfile(
                depth=policy.get('depth', qos.depth),
                reliability=(
                    ReliabilityPolicy.RELIABLE
                    if policy.get('reliability') == 'reliable'
                    else ReliabilityPolicy.BEST_EFFORT
                    if policy.get('reliability') == 'best_effort'
                    else qos.reliability
                ),
            )
            for topic, policy in (qos_overrides or {}).items()
        }
        self.frame_prefix = frame_prefix
        self.frames = sensor_frames or {}
        self.custom_messages = custom_messages
        self.range_fov = range_fov
        self.alias_rules = topic_aliases or {}
        self.aliases = {}
        self.devices = {}
        self.public_topics = {}

    def sync(self, devices):
        active = {row['topic']: row['revision'] for row in devices
                  if row['topic'] and row['online'] and not row['stale'] and row['metadata_ready']}
        for topic in self.devices.keys() | self.public_topics.keys():
            if topic not in active or active[topic] != self.devices.get(topic):
                for group in self.public_topics.pop(topic, {}).values():
                    for public_topic in group.values():
                        self.cache.remove_topic(public_topic)
        self.devices = active
        selected = bindings(self.alias_rules, devices)
        for alias, identity in self.aliases.items():
            if selected.get(alias) != identity:
                self.cache.remove_topic(alias)
        self.aliases = selected
        for row in devices:
            row['aliases'] = [alias for alias, (topic, _, _) in selected.items()
                              if topic == row['topic']]
            row['public_topics'] = {
                group: dict(topics)
                for group, topics in self.public_topics.get(row['topic'], {}).items()
            }

    def frame(self, device):
        identity = f'{device.key.bus}:{device.key.address}'
        return self.frames.get(
            identity, self.frame_prefix + '_' + device.key.frame_suffix
        )

    def publish(self, device, group, sample):
        base = sensor_topic(device.device_type, device.key)
        frame = self.frame(device)
        stamp = Time(nanoseconds=sample['stamp_ns']).to_msg()
        values = sample['values']

        def emit(suffix, msg):
            if hasattr(msg, 'header'):
                msg.header.frame_id, msg.header.stamp = frame, stamp
            public_topic = measurement_topic(device, group, suffix)
            # User aliases reserve their exact paths even while unbound. An
            # automatically generated output must never take over that name.
            if public_topic not in self.alias_rules:
                qos = self.qos_overrides.get(public_topic)
                self.cache.get(public_topic, type(msg), qos).publish(msg)
                self.public_topics.setdefault(base, {}).setdefault(group, {})[
                    suffix
                ] = public_topic
            if group == 'x':
                for alias, identity in self.aliases.items():
                    if identity == (base, device.revision, suffix):
                        publisher = self.cache.get(alias, type(msg), self.qos_overrides.get(alias))
                        publisher.publish(msg)

        generic = DeviceSample()
        generic.bus, generic.address = device.key.bus, device.key.address
        generic.device_type, generic.group = device.device_type, group
        generic.values_json = json_text(values)
        generic.device_time_us = (
            float(sample['timestamp_us']) if sample['timestamp_us'] is not None else math.nan
        )
        generic.poll_time_us = (
            float(sample['poll_timestamp_us'])
            if sample['poll_timestamp_us'] is not None
            else math.nan
        )
        generic.received_at = Time(nanoseconds=sample['receipt_ns']).to_msg()
        generic.time_quality = sample['time_quality']
        generic.overflow = int(sample['overflow'])
        emit('sample', generic)
        emit(
            'data',
            String(
                data=json_text(
                    {
                        'bus': device.key.bus,
                        'address': device.key.address,
                        'type': device.device_type,
                        'group': group,
                        'timestamp_ms': sample['timestamp_ms'],
                        'time_quality': sample['time_quality'],
                        'values': values,
                    }
                )
            ),
        )

        def value(name):
            entry = values[name]
            return float(entry['si_value'] if entry['si_value'] is not None else entry['value'])

        def emit_image(suffix, width, height, pixels):
            msg = Image()
            msg.width, msg.height = width, height
            msg.encoding = '32FC1'
            msg.is_bigendian = 0
            msg.step = width * 4
            msg.data = float32_image_data(width, height, pixels)
            emit(suffix, msg)

        if (
            all(n in values for n in ('gx', 'gy', 'gz', 'ax', 'ay', 'az'))
            and all(values[n]['si_unit'] == 'rad/s' for n in ('gx', 'gy', 'gz'))
            and all(values[n]['si_unit'] == 'm/s^2' for n in ('ax', 'ay', 'az'))
        ):
            # Six-axis data has no orientation estimate. Unknown covariances stay
            # zero; unavailable orientation is explicitly marked per sensor_msgs.
            msg = Imu()
            msg.orientation_covariance[0] = -1.0
            msg.angular_velocity.x, msg.angular_velocity.y, msg.angular_velocity.z = [
                value(n) for n in ('gx', 'gy', 'gz')
            ]
            msg.linear_acceleration.x, msg.linear_acceleration.y, msg.linear_acceleration.z = [
                value(n) for n in ('ax', 'ay', 'az')
            ]
            emit('data_raw', msg)
            if self.custom_messages:
                custom = Imu6()
                for name in ('gx', 'gy', 'gz', 'ax', 'ay', 'az'):
                    setattr(custom, name, value(name))
                emit('imu/axiom', custom)

        distance = values.get('dist') or values.get('distance')
        if (distance and distance.get('si_unit') == 'm'
                and isinstance(distance['si_value'], list)):
            if distance['meta'].get('vt') == 'zonegrid':
                side, pixels = zone_grid(values, distance)
                emit_image(image_suffix(device, 'range'), side, side, pixels)
        elif distance and distance.get('si_unit') == 'm':
            valid = bool(distance['valid'])
            msg = Range()
            msg.radiation_type = Range.INFRARED
            msg.field_of_view = float(self.range_fov)
            limits = distance['meta'].get('r', [0, 1000])
            scale = 0.001 if distance['unit'] == 'mm' else 1.0
            msg.min_range, msg.max_range = float(limits[0]) * scale, float(limits[1]) * scale
            msg.range = float(distance['si_value']) if valid else math.nan
            emit('range', msg)
            if self.custom_messages and device.device_type.upper() == 'VL53L4CD':
                custom = VL53L4CDReading()
                custom.valid = valid
                custom.distance_m = msg.range
                raw = distance['raw']
                custom.distance_mm = max(0, min(0xFFFFFFFF, int(raw)))
                emit('range/raw', custom)

        temperature = values.get('temperature')
        if temperature:
            readings = temperature['value']
            if isinstance(readings, list):
                resolution = temperature['meta'].get('resolution', '')
                if 'x' in resolution:
                    width, height = (int(n) for n in resolution.split('x'))
                    if width * height != len(readings):
                        raise ValueError('Thermal grid dimensions do not match its pixels')
                    msg = ThermalGrid()
                    msg.width, msg.height = width, height
                    msg.temperature_c = [float(v) for v in readings]
                    emit('grid', msg)
                    if temperature.get('si_unit') == 'degC':
                        emit_image(image_suffix(device, 'thermal'), width, height,
                                   temperature['si_value'])
            elif temperature.get('si_unit') == 'degC':
                msg = Temperature()
                msg.temperature = float(temperature['si_value'])
                emit('temperature', msg)
        humidity = values.get('humidity')
        if humidity and humidity.get('si_unit') == 'fraction':
            msg = RelativeHumidity()
            msg.relative_humidity = float(humidity['si_value'])
            emit('humidity', msg)

        if device.device_type in ('RoboticalServo', 'RoboticalSoloServo') and 'angle' in values:
            msg = JointState()
            msg.name = [frame + '_joint']
            msg.position = [value('angle')]
            # Firmware current/velocity fields have no unit contract here; do not
            # publish them as effort or radians/sec by guessing their meaning.
            emit('joint_states', msg)

        battery = next(
            (values[n] for n in ('battV', 'batt_v', 'batteryVoltage') if n in values), None
        )
        if battery:
            voltage = float(battery['value'])
            msg = BatteryState()
            msg.voltage = voltage
            msg.present = True
            for field in (
                'temperature',
                'current',
                'charge',
                'capacity',
                'design_capacity',
                'percentage',
            ):
                setattr(msg, field, math.nan)
            emit('battery', msg)
            if self.custom_messages:
                emit('power/raw', AxiomPowerState(batt_v=voltage))
