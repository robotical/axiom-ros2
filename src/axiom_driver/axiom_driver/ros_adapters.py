"""ROS message contracts layered over decoded firmware samples."""

import json
import math

from axiom_interfaces.msg import AxiomPowerState, DeviceSample, Imu6, ThermalGrid, VL53L4CDReading
from rclpy.qos import QoSProfile, ReliabilityPolicy
from rclpy.time import Time
from sensor_msgs.msg import (
    BatteryState, Illuminance, Image, Imu, JointState, Range, RelativeHumidity, Temperature,
)
from std_msgs.msg import Bool, Float64, String

from .core.aliases import bindings
from .core.grids import float32_image_data, zone_grid
from .core.ros_mappings import mapped_scalar_output, parse_ros_mappings
from .core.scalars import scalar_output
from .core.topic_names import attribute_topic, image_suffix, measurement_topic, sensor_topic
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
        self.output_info = {}
        self._logger = node.get_logger()
        self._mapping_state = {}

    def sync(self, devices):
        active = {row['topic']: row['revision'] for row in devices
                  if row['topic'] and row['online'] and not row['stale'] and row['metadata_ready']}
        for topic in self.devices.keys() | self.public_topics.keys():
            if topic not in active or active[topic] != self.devices.get(topic):
                self._mapping_state.pop(topic, None)
                self.output_info.pop(topic, None)
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
            row['output_info'] = {
                group: {suffix: dict(info) for suffix, info in outputs.items()}
                for group, outputs in self.output_info.get(row['topic'], {}).items()
            }

    def frame(self, device):
        identity = f'{device.key.bus}:{device.key.address}'
        return self.frames.get(
            identity, self.frame_prefix + '_' + device.key.frame_suffix
        )

    def _mapped_outputs(self, device, values):
        base = sensor_topic(device.device_type, device.key)
        state = self._mapping_state.get(base)
        if state is None or state[0] != device.revision:
            rules, warnings = parse_ros_mappings(device.metadata)
            state = (device.revision, rules, set())
            self._mapping_state[base] = state
        else:
            warnings = []
        outputs = {}
        for name, message_type in state[1].items():
            if name not in values:
                continue  # Another payload group may carry this attribute.
            try:
                outputs[name] = mapped_scalar_output(message_type, values[name])
            except ValueError as exc:
                warnings.append(f'ros.attributes.{name}: {exc}')
        for warning in warnings:
            if warning not in state[2]:
                state[2].add(warning)
                self._logger.warning(f'{base}: {warning}; keeping automatic outputs')
        return outputs

    def publish(self, device, group, sample):
        base = sensor_topic(device.device_type, device.key)
        frame = self.frame(device)
        stamp = Time(nanoseconds=sample['stamp_ns']).to_msg()
        values = sample['values']
        mapped = self._mapped_outputs(device, values)
        consumed = set()

        def emit(suffix, msg, unit=None):
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
                self.output_info.setdefault(base, {}).setdefault(group, {})[suffix] = {
                    'message_type': (
                        type(msg).__module__.split('.')[0] + '/msg/' + type(msg).__name__),
                    'unit': unit,
                }
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

        def emit_image(suffix, width, height, pixels, unit):
            msg = Image()
            msg.width, msg.height = width, height
            msg.encoding = '32FC1'
            msg.is_bigendian = 0
            msg.step = width * 4
            msg.data = float32_image_data(width, height, pixels)
            emit(suffix, msg, unit)

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
            consumed.update(('gx', 'gy', 'gz', 'ax', 'ay', 'az'))
            if self.custom_messages:
                custom = Imu6()
                for name in ('gx', 'gy', 'gz', 'ax', 'ay', 'az'):
                    setattr(custom, name, value(name))
                emit('imu/axiom', custom)

        distance_name = next((n for n in ('dist', 'distance') if n in values), None)
        distance = values.get(distance_name)
        if (distance and distance.get('si_unit') == 'm'
                and isinstance(distance['si_value'], list)):
            if distance['meta'].get('vt') == 'zonegrid':
                side, pixels = zone_grid(values, distance)
                emit_image(image_suffix(device, 'range'), side, side, pixels, 'm')
                consumed.update((distance_name, distance['meta']['vo']['gridAttr'],
                                 distance['meta']['vo']['statusAttr']))
        elif distance and distance.get('si_unit') == 'm':
            valid = bool(distance['valid'])
            msg = Range()
            msg.radiation_type = Range.INFRARED
            msg.field_of_view = float(self.range_fov)
            limits = distance['meta'].get('r', [0, 1000])
            scale = 0.001 if distance['unit'] == 'mm' else 1.0
            msg.min_range, msg.max_range = float(limits[0]) * scale, float(limits[1]) * scale
            msg.range = float(distance['si_value']) if valid else math.nan
            emit('range', msg, 'm')
            consumed.add(distance_name)
            if distance['meta'].get('vft'):
                consumed.add(distance['meta']['vft'])
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
                    emit('grid', msg, temperature['si_unit'] or temperature['unit'])
                    consumed.add('temperature')
                    if temperature.get('si_unit') == 'degC':
                        emit_image(image_suffix(device, 'thermal'), width, height,
                                   temperature['si_value'], 'degC')
            elif temperature.get('si_unit') == 'degC' and 'temperature' not in mapped:
                msg = Temperature()
                msg.temperature = float(temperature['si_value'])
                emit('temperature', msg, 'degC')
                consumed.add('temperature')
        humidity = values.get('humidity')
        if humidity and humidity.get('si_unit') == 'fraction' and 'humidity' not in mapped:
            msg = RelativeHumidity()
            msg.relative_humidity = float(humidity['si_value'])
            emit('humidity', msg, 'fraction')
            consumed.add('humidity')

        if device.device_type in ('RoboticalServo', 'RoboticalSoloServo') and 'angle' in values:
            msg = JointState()
            msg.name = [frame + '_joint']
            msg.position = [value('angle')]
            # Firmware current/velocity fields have no unit contract here; do not
            # publish them as effort or radians/sec by guessing their meaning.
            emit('joint_states', msg, 'rad')
            consumed.add('angle')

        battery_name = next(
            (n for n in ('battV', 'batt_v', 'batteryVoltage') if n in values), None)
        battery = values.get(battery_name)
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
            emit('battery', msg, 'V')
            consumed.add(battery_name)
            if self.custom_messages:
                emit('power/raw', AxiomPowerState(batt_v=voltage), 'V')

        for name, entry in values.items():
            if name in mapped:
                output = mapped[name]
            elif name in consumed:
                continue
            else:
                output = scalar_output(name, entry)
            if output is None:
                continue
            kind, reading, unit = output
            if kind == 'illuminance':
                msg = Illuminance(illuminance=reading, variance=0.0)
            elif kind == 'temperature':
                msg = Temperature(temperature=reading, variance=0.0)
            elif kind == 'humidity':
                msg = RelativeHumidity(relative_humidity=reading, variance=0.0)
            else:
                msg = {'float': Float64, 'bool': Bool, 'string': String}[kind](data=reading)
            emit(attribute_topic(name), msg, unit)
