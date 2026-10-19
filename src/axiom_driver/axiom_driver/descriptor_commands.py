"""Descriptor-driven command topics and acknowledged configuration services."""

from collections import OrderedDict
import threading
import time

from axiom_interfaces.srv import DeviceCommand
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import ColorRGBA, Float64

from .core.commands import command_format
from .core.output_commands import output_topics, output_values
from .core.registry import DeviceKey, topic_token
from .ros_adapters import json_text


def command_token(name):
    if name == '_conf.rate':
        return 'set_sample_rate'
    token = topic_token(name)
    return token if token[:1].isalpha() else 'command' + token


class DescriptorCommands:
    """Keep only the latest target per input, dispatched by the pipeline worker."""

    def __init__(self, node):
        self.node = node
        self.services = {}
        self.subscriptions = {}
        self.active = {}
        self.pending = OrderedDict()
        self.sent = {}
        self.lock = threading.Lock()
        self.group = ReentrantCallbackGroup()
        self.qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                              durability=DurabilityPolicy.VOLATILE)

    def sync(self, devices):
        """Advertise topic inputs and services only for live resolved device revisions."""
        services, topics = {}, {}
        for row in devices:
            row['commands'], row['command_topics'] = [], []
            if not row['online'] or row['stale'] or not row['metadata_ready']:
                continue
            key = DeviceKey(row['bus'], row['address'])
            device = self.node.pipeline.registry.devices[key]
            for action in device.metadata.get('actions', []):
                name = action.get('n')
                if not isinstance(name, str) or not name:
                    continue
                try:
                    command_format(action)
                except ValueError:
                    # Custom formats remain metadata-only, as for configuration services.
                    continue
                try:
                    specs = output_topics(device.metadata, action)
                except (ValueError, TypeError, OverflowError) as error:
                    self.node._issue(f'{row["topic"]}/{name}: {error}')
                    continue
                path = row['topic'] + '/commands/' + command_token(name)
                if specs:
                    for spec in specs:
                        topic = path + ('/pixel_' + str(spec['pixel']) if 'pixel' in spec else '')
                        identity = (key, device.revision, name, spec.get('pixel'))
                        topics[topic] = (identity, action, spec)
                        row['command_topics'].append({
                            'name': name, 'topic': topic, 'unit': spec['unit'],
                            'kind': spec['kind'], 'descriptor': action,
                            'message_type': 'std_msgs/msg/' + (
                                'Float64' if spec['kind'] == 'angle' else 'ColorRGBA'),
                            **({'pixel': spec['pixel']} if 'pixel' in spec else {}),
                        })
                else:
                    identity = (key, device.revision, name)
                    services[path] = identity
                    row['commands'].append({'name': name, 'service': path, 'descriptor': action})
        for path, (service, identity) in list(self.services.items()):
            if services.get(path) != identity:
                self.node.destroy_service(service)
                del self.services[path]
        with self.lock:
            for path in list(self.active):
                if path not in topics or self.active[path] != topics[path][0]:
                    self.active.pop(path)
                    self.pending.pop(path, None)
                    self.sent.pop(path, None)
            self.active.update({path: item[0] for path, item in topics.items()})
        for path, (subscription, identity) in list(self.subscriptions.items()):
            if path not in topics or topics[path][0] != identity:
                self.node.destroy_subscription(subscription)
                del self.subscriptions[path]
        for path, (identity, action, spec) in topics.items():
            if path not in self.subscriptions:
                kind = Float64 if spec['kind'] == 'angle' else ColorRGBA
                subscription = self.node.create_subscription(
                    kind, path, self.topic_callback(path, identity, action, spec), self.qos)
                self.subscriptions[path] = (subscription, identity)
        for path, identity in services.items():
            if path not in self.services:
                self.services[path] = (self.node.create_service(
                    DeviceCommand, path, self.service_callback(*identity),
                    callback_group=self.group), identity)

    def topic_callback(self, path, identity, action, spec):
        """Validate input without blocking the ROS executor on firmware I/O."""
        def receive(message):
            try:
                value = message.data if spec['kind'] == 'angle' else (
                    message.r, message.g, message.b)
                values = output_values(action, spec, value)
            except (ValueError, TypeError, OverflowError) as error:
                self.node._issue(f'{path}: rejected command: {error}')
                return
            with self.lock:
                if self.active.get(path) != identity:
                    return
                self.pending.pop(path, None)
                self.pending[path] = (identity, values, self.node.session.generation,
                                      time.monotonic())
        return receive

    def dispatch_one(self):
        """Send at most one current target, allowing acquisition between commands."""
        with self.lock:
            if not self.pending:
                return
            path, (identity, values, generation, received) = self.pending.popitem(last=False)
            if (self.active.get(path) != identity or self.sent.get(path) == values
                    or generation != self.node.session.generation
                    or time.monotonic() - received > self.node.config['rpc_default_timeout']):
                return
            self.sent.pop(path, None)
        key, revision, name, _ = identity
        try:
            self.node.pipeline.command(key, revision, name, values,
                                       self.node.config['stale_after_s'])
        except Exception as error:
            self.node._issue(f'{path}: command failed: {error}')
        else:
            with self.lock:
                if self.active.get(path) == identity:
                    self.sent[path] = values

    def service_callback(self, key, revision, name):
        def handle(request, response):
            def run():
                def command():
                    try:
                        result = self.node.pipeline.command(
                            key, revision, name, request.values, self.node.config['stale_after_s'])
                    finally:
                        if name in ('enable', 'off'):
                            # Discrete control must not replay a target queued before its reply.
                            with self.lock:
                                for path, identity in self.active.items():
                                    if identity[0] == key:
                                        self.pending.pop(path, None)
                                        self.sent.pop(path, None)
                    if name == '_conf.rate':
                        self.node._discard_data()
                    return result
                result = self.node._worker_call(command)
                response.response_json = json_text(result)
            return self.node._service(response, run)
        return handle

    def clear(self):
        """Retire interfaces and discard targets across session changes or shutdown."""
        with self.lock:
            self.active.clear()
            self.pending.clear()
            self.sent.clear()
        for subscription, _ in self.subscriptions.values():
            self.node.destroy_subscription(subscription)
        self.subscriptions.clear()
        for service, _ in self.services.values():
            self.node.destroy_service(service)
        self.services.clear()
