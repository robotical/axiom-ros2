"""ROS services whose names and argument metadata come from live descriptors."""

from axiom_interfaces.srv import DeviceCommand
from rclpy.callback_groups import ReentrantCallbackGroup

from .core.commands import command_format
from .core.registry import DeviceKey, topic_token
from .ros_adapters import json_text


def command_token(name):
    if name == '_conf.rate':
        return 'set_sample_rate'
    token = topic_token(name)
    return token if token[:1].isalpha() else 'command' + token


class DescriptorServices:
    def __init__(self, node):
        self.node = node
        self.services = {}
        self.group = ReentrantCallbackGroup()

    def sync(self, devices):
        desired = {}
        for row in devices:
            if not row['online'] or row['stale'] or not row['metadata_ready']:
                continue
            key = DeviceKey(row['bus'], row['address'])
            device = self.node.pipeline.registry.devices[key]
            row['commands'] = []
            for action in device.metadata.get('actions', []):
                name = action.get('n')
                if not isinstance(name, str) or not name:
                    continue
                try:
                    command_format(action)
                except ValueError:
                    continue
                service = row['topic'] + '/commands/' + command_token(name)
                desired[service] = (key, device.revision, name)
                row['commands'].append({'name': name, 'service': service, 'descriptor': action})
        for name in list(self.services):
            service, identity = self.services[name]
            if desired.get(name) != identity:
                self.node.destroy_service(service)
                del self.services[name]
        for name, identity in desired.items():
            if name not in self.services:
                callback = self.callback(*identity)
                self.services[name] = (self.node.create_service(
                    DeviceCommand, name, callback, callback_group=self.group), identity)

    def callback(self, key, revision, name):
        def handle(request, response):
            def run():
                def command():
                    result = self.node.pipeline.command(
                        key, revision, name, request.values, self.node.config['stale_after_s'])
                    if name == '_conf.rate':
                        self.node._discard_data()
                    return result
                result = self.node._worker_call(command)
                response.response_json = json_text(result)
            return self.node._service(response, run)
        return handle

    def clear(self):
        for service, _ in self.services.values():
            self.node.destroy_service(service)
        self.services.clear()
