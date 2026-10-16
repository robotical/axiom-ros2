"""Discover Axioms and run one host bridge per physical board."""

from concurrent.futures import ThreadPoolExecutor
import json
import os
from time import monotonic

import rclpy
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from rclpy.qos import DurabilityPolicy, QoSProfile
from serial.tools.list_ports import comports
from std_msgs.msg import String

from .axiom_bridge_node import AxiomBridgeNode
from .config import board_parameters, load_discovery_config
from .core.discovery import probe_axiom_firmware, probe_network_firmware
from .core.ownership import endpoint_key, normalise_board_id

USB_CANDIDATE_IDS = {(0x303A, 0x1001)}
PROBE_RETRY_DELAY_S = 5.0


class AxiomDiscoveryNode(Node):

    default_wifi = True

    def __init__(self, port_provider=None, network_provider=None, **kwargs):
        super().__init__(kwargs.pop('node_name', 'axiom_discovery'), **kwargs)
        filename = self.declare_parameter(
            'boards_file', os.environ.get('AXIOM_ROS_BOARDS_FILE', ''),
        ).value
        settings, self._rules = load_discovery_config(filename)
        self._usb = self.declare_parameter('usb', settings['usb']).value
        self._wifi = self.declare_parameter('wifi', settings['wifi'] and self.default_wifi).value
        self._include_unconfigured = self.declare_parameter(
            'include_unconfigured', settings['include_unconfigured'],
        ).value
        self._port_provider = comports if port_provider is None else port_provider
        self._network = None
        if self._wifi:
            if network_provider is None:
                from .core.network_discovery import NetworkDiscovery

                network_provider = NetworkDiscovery()
            self._network = network_provider
        self._probe_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='axiom-probe')
        self._probe_futures = {}
        self._probe_retries = {}
        self._verified = {}
        self._rejected = set()
        self._drivers = {}  # Firmware MAC -> (endpoint, bridge node).
        self._intent = {}  # Retain explicit disconnect/acquisition choices over replug.
        self._usb_endpoints = set()
        self._last_status = self._last_inventory = None
        self._enum_error = None
        self._selection_errors = {}
        self._bindings = {}  # Remember a configured endpoint's verified physical identity.
        self._inventory = self.create_publisher(
            String, '~/boards', QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL),
        )
        self._timer = self.create_timer(2.0, self._scan)
        self._scan()

    def _candidates(self):
        """Keep the last USB inventory on enumeration failure, rather than disconnecting."""
        if self._usb:
            try:
                ports = tuple(self._port_provider())
                explicit = {
                    rule['endpoint'] for rule in self._rules.values()
                    if rule['transport'] == 'serial' and rule['endpoint']
                }
                self._usb_endpoints = {
                    ('serial', port.device) for port in ports
                    if (port.vid, port.pid) in USB_CANDIDATE_IDS
                    or endpoint_key('serial', port.device) in explicit
                }
                self._enum_error = None
            except OSError as exc:
                if str(exc) != self._enum_error:
                    self.get_logger().warning(f'USB enumeration failed: {exc}')
                self._enum_error = str(exc)
        candidates = set(self._usb_endpoints)
        if self._network is not None:
            candidates.update(('ws', uri) for uri in self._network.snapshot())
        # Explicit network endpoints work even on networks that block multicast.
        candidates.update(
            ('ws', rule['address']) for rule in self._rules.values()
            if rule['transport'] == 'ws' and rule['address']
        )
        return candidates

    def _scan(self):
        candidates = self._candidates()
        for identity, (endpoint, driver) in list(self._drivers.items()):
            if driver._identity_changed:
                self._verified.pop(endpoint, None)
                self._stop_driver(identity)
        for endpoint in set(self._probe_futures) - candidates:
            self._probe_futures.pop(endpoint).cancel()
        for records in (self._verified, self._probe_retries):
            for endpoint in set(records) - candidates:
                del records[endpoint]
        self._rejected.intersection_update(candidates)

        for endpoint, future in list(self._probe_futures.items()):
            if not future.done():
                continue
            del self._probe_futures[endpoint]
            try:
                firmware = future.result()
            except Exception as exc:
                previous = self._probe_retries.get(endpoint)
                message = f'Axiom probe failed for {endpoint[1]}: {exc}'
                if previous is None or previous[1] != message:
                    self.get_logger().warning(message)
                self._probe_retries[endpoint] = (monotonic() + PROBE_RETRY_DELAY_S, message)
                continue
            self._probe_retries.pop(endpoint, None)
            identity = normalise_board_id(firmware.get('MAC')) if firmware else None
            if identity is None:
                self._rejected.add(endpoint)
                message = (
                    'Axiom firmware has no valid MAC identity; use an explicit bridge launch'
                    if firmware else 'USB/network candidate not recognised as an Axiom'
                )
                self.get_logger().warning(f'{endpoint[1]}: {message}')
                continue
            self._verified[endpoint] = identity
            self.get_logger().info(f'Axiom verified: {endpoint[1]} (id={identity})')

        self._reconcile()
        for endpoint in sorted(candidates, key=lambda item: (item[0] != 'serial', item[1])):
            if (endpoint in self._verified or endpoint in self._rejected
                    or endpoint in self._probe_futures):
                continue
            retry = self._probe_retries.get(endpoint)
            if retry and monotonic() < retry[0]:
                continue
            probe = probe_axiom_firmware if endpoint[0] == 'serial' else probe_network_firmware
            self._probe_futures[endpoint] = self._probe_executor.submit(probe, endpoint[1])

        status = tuple(sorted(candidates))
        if status != self._last_status:
            self._last_status = status
            self.get_logger().info(
                'Waiting for an Axiom...' if not status else
                'Axiom candidates: ' + ', '.join(address for _, address in status),
            )
        self._publish_inventory()

    def _selection(self, identity, endpoints):
        matches = [
            (namespace, rule) for namespace, rule in self._rules.items()
            if rule['id'] == identity or self._bindings.get(identity) == namespace
            or not rule['id'] and any(
                endpoint_key(*endpoint) == rule['endpoint'] for endpoint in endpoints)
        ]
        if len(matches) > 1:
            raise ValueError('Multiple board entries match this physical Axiom')
        if matches:
            namespace, rule = matches[0]
            self._bindings[identity] = namespace
            if rule['transport']:
                endpoints = [item for item in endpoints if item[0] == rule['transport']]
            params = dict(rule['parameters'])
        elif self._include_unconfigured:
            namespace = '/axiom_' + identity
            params = board_parameters(namespace, {})
        else:
            return None
        if not endpoints:
            return None
        endpoint = min(endpoints, key=lambda item: (item[0] != 'serial', item[1]))
        params['transport'] = endpoint[0]
        params['serial.port' if endpoint[0] == 'serial' else 'device_uri'] = endpoint[1]
        return namespace, endpoint, params

    def _reconcile(self):
        boards = {}
        for endpoint, identity in self._verified.items():
            boards.setdefault(identity, []).append(endpoint)
        selected, namespaces, frames = {}, {}, {}
        for identity, endpoints in sorted(boards.items()):
            try:
                choice = self._selection(identity, endpoints)
                if choice is None:
                    continue
                namespace, endpoint, params = choice
                if namespace in namespaces or params['frame_id'] in frames:
                    raise ValueError('Board namespace or frame_id collides with another board')
                namespaces[namespace] = frames[params['frame_id']] = identity
                selected[identity] = choice
                self._selection_errors.pop(identity, None)
            except ValueError as exc:
                if self._selection_errors.get(identity) != str(exc):
                    self.get_logger().warning(f'Axiom {identity}: {exc}')
                self._selection_errors[identity] = str(exc)

        for identity, (endpoint, _) in list(self._drivers.items()):
            if identity not in selected or selected[identity][1] != endpoint:
                self._stop_driver(identity)
        for identity, (namespace, endpoint, params) in selected.items():
            if identity not in self._drivers:
                self._start_driver(identity, namespace, endpoint, params)

    def _create_driver(self, namespace, params):
        return AxiomBridgeNode(
            context=self.context, namespace=namespace, use_global_arguments=False,
            parameter_overrides=[Parameter(name, value=value) for name, value in params.items()],
        )

    def _start_driver(self, identity, namespace, endpoint, params):
        executor = self.executor
        if executor is None:
            raise RuntimeError('Discovery must be added to an executor first')
        driver = self._create_driver(namespace, params)
        driver._expected_identity = identity
        if identity in self._intent:
            driver._desired_connection, driver._desired_rate = self._intent[identity]
        try:
            executor.add_node(driver)
        except Exception:
            driver.destroy_node()
            raise
        self._drivers[identity] = (endpoint, driver)
        self.get_logger().info(f'Host driver started: {namespace} at {endpoint[1]}')

    def _stop_driver(self, identity):
        _, driver = self._drivers.pop(identity)
        self._intent[identity] = driver._desired_connection, driver._desired_rate
        if driver.executor is not None:
            driver.executor.remove_node(driver)
        driver.destroy_node()
        self.get_logger().info(f'Host driver stopped: {identity}')

    def _publish_inventory(self):
        inventory = json.dumps([
            {'id': identity, 'namespace': driver.get_namespace(),
             'transport': endpoint[0], 'address': endpoint[1],
             'connected': driver.session.connected}
            for identity, (endpoint, driver) in sorted(self._drivers.items())
        ], sort_keys=True)
        if inventory != self._last_inventory:
            self._last_inventory = inventory
            self._inventory.publish(String(data=inventory))

    def destroy_node(self):
        """Release managed nodes and wait for bounded verification work to finish."""
        self._timer.cancel()
        for identity in list(self._drivers):
            self._stop_driver(identity)
        if self._network is not None:
            self._network.close()
        self._probe_executor.shutdown(wait=True, cancel_futures=True)
        return super().destroy_node()


def run(factory, args=None):
    rclpy.init(args=args)
    node = None
    executor = SingleThreadedExecutor()
    try:
        node = factory()
        executor.add_node(node)
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


def main(args=None):
    run(AxiomDiscoveryNode, args)
