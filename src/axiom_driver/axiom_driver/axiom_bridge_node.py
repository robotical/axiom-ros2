"""ROS 2 adapter for one acknowledged Axiom firmware session."""

from concurrent.futures import Future, ThreadPoolExecutor, TimeoutError
import json
import math
import queue
import threading
import time

from axiom_interfaces.srv import (
    Connect,
    Disconnect,
    GetConnectionState,
    Ping,
    PublishedDataSubscription,
    RicRestUrl,
    SetSampleRate,
)
from diagnostic_msgs.msg import DiagnosticArray, DiagnosticStatus, KeyValue
from rcl_interfaces.msg import ParameterDescriptor
import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.executors import ExternalShutdownException, MultiThreadedExecutor
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from std_msgs.msg import String

from .config import DEFAULT_PARAMETERS
from .core.aliases import validate_aliases
from .core.pipeline import Pipeline
from .core.registry import DeviceKey
from .core.rpc import SessionError
from .core.session import Session
from .core.timing import Receipt
from .descriptor_services import DescriptorServices
from .ros_adapters import json_text, RosAdapters


class AxiomBridgeNode(Node):
    def __init__(self, **kwargs):
        super().__init__('axiom_bridge_node', **kwargs)
        defaults = DEFAULT_PARAMETERS
        for name, value in defaults.items():
            self.declare_parameter(name, value, ParameterDescriptor(read_only=True))
        self.config = {name: self.get_parameter(name).value for name in defaults}
        self._validate_config()
        qos = QoSProfile(
            depth=self.config['sensor_qos.depth'],
            reliability=(
                ReliabilityPolicy.RELIABLE
                if self.config['sensor_qos.reliability'] == 'reliable'
                else ReliabilityPolicy.BEST_EFFORT
            ),
        )
        inventory_qos = QoSProfile(
            depth=1,
            reliability=ReliabilityPolicy.RELIABLE,
            durability=DurabilityPolicy.TRANSIENT_LOCAL,
        )
        self.inventory_pub = self.create_publisher(String, 'devices', inventory_qos)
        self.metadata_pub = self.create_publisher(String, 'device_metadata', inventory_qos)
        self.raw_pub = self.create_publisher(String, 'raw/devjson', 10)
        self.console_pub = self.create_publisher(String, 'serial_console', 10)
        self.diagnostic_pub = self.create_publisher(DiagnosticArray, 'diagnostics', 10)
        self.adapters = RosAdapters(
            self,
            qos,
            self.config['frame_id'],
            json.loads(self.config['sensor_frames']),
            self.config['publish_custom_messages'],
            self.config['range.field_of_view'],
            json.loads(self.config['sensor_qos.overrides']),
            json.loads(self.config['topic_aliases']),
        )
        self._state_lock = threading.Lock()
        self._connection_lock = threading.Lock()
        self._rpc_slots = threading.BoundedSemaphore(2)
        self._data = queue.Queue(maxsize=self.config['receive_queue_depth'])
        self._commands = queue.Queue(maxsize=16)
        self._stop = threading.Event()
        self._desired_connection = self.config['auto_connect']
        self._desired_rate = self.config['publish_rate_hz'] if self.config['autosub'] else 0.0
        self._subscribed = False
        self._next_reconnect = 0.0
        self._connect_task = None
        self._last_rx = None
        self._last_issue = ''
        self._last_issue_time = 0.0
        self._queue_drops = 0
        self._inventory = []
        self._metadata_text = ''
        self._counts = {}
        self._active_generation = -1
        self._next_inventory = 0.0
        self._connector = ThreadPoolExecutor(max_workers=1, thread_name_prefix='axiom-connect')
        self.session = Session(
            self._receive,
            self._session_state,
            self._issue,
            lambda line: self.console_pub.publish(String(data=line)),
        )
        self.pipeline = Pipeline(
            self.session.request,
            self.adapters.publish,
            self._inventory_changed,
            self._issue,
            self.config['metadata_refresh_s'],
        )
        self.descriptor_services = DescriptorServices(self)
        self._worker = threading.Thread(target=self._work, name='axiom-decode', daemon=True)
        self._worker.start()
        group = ReentrantCallbackGroup()
        for srv, name, callback in (
            (Connect, 'connect', self.handle_connect),
            (Disconnect, 'disconnect', self.handle_disconnect),
            (GetConnectionState, 'get_connection_state', self.handle_get_state),
            (Ping, 'ping', self.handle_ping),
            (RicRestUrl, 'ric_rest_url', self.handle_ric_rest_url),
            (PublishedDataSubscription, 'publish_data_subscription', self.handle_subscription),
            (SetSampleRate, 'set_sample_rate', self.handle_sample_rate),
        ):
            self.create_service(srv, name, callback, callback_group=group)
        self.create_timer(0.25, self._maintain_connection, callback_group=group)
        self.create_timer(1.0, self._diagnostics, callback_group=group)
        self.get_logger().info(
            'One upstream acquisition stream; use ROS topics for additional consumers'
        )

    def _validate_config(self):
        cfg = self.config
        if cfg['transport'] not in ('serial', 'ws'):
            raise ValueError('transport must be serial or ws')
        if cfg['sensor_qos.reliability'] not in ('reliable', 'best_effort'):
            raise ValueError('sensor_qos.reliability must be reliable or best_effort')
        if (
            not 1 <= cfg['sensor_qos.depth'] <= 10000
            or not 1 <= cfg['receive_queue_depth'] <= 10000
        ):
            raise ValueError('Queue depths must be 1..10000')
        for name in (
            'rpc_default_timeout',
            'reconnect_interval',
            'metadata_refresh_s',
            'stale_after_s',
        ):
            if not math.isfinite(cfg[name]) or cfg[name] <= 0:
                raise ValueError(f'{name} must be positive and finite')
        if cfg['rpc_default_timeout'] > 60:
            raise ValueError('rpc_default_timeout exceeds 60 seconds')
        if not math.isfinite(cfg['publish_rate_hz']) or not 0 <= cfg['publish_rate_hz'] <= 1000:
            raise ValueError('publish_rate_hz must be 0..1000')
        if cfg['publish_trigger'] not in ('time', 'change', 'timeorchange'):
            raise ValueError('Invalid publish_trigger')
        if (
            not math.isfinite(cfg['range.field_of_view'])
            or not 0 <= cfg['range.field_of_view'] <= math.pi
        ):
            raise ValueError('range.field_of_view must be 0..pi radians')
        overrides = json.loads(cfg['sensor_qos.overrides'])
        if not isinstance(overrides, dict):
            raise ValueError('sensor_qos.overrides must be a JSON object')
        for topic, policy in overrides.items():
            if not topic or topic.startswith('/') or not isinstance(policy, dict):
                raise ValueError('QoS overrides require relative topic names and policy objects')
            if set(policy) - {'depth', 'reliability'}:
                raise ValueError('QoS overrides support depth and reliability')
            if policy.get('reliability', 'best_effort') not in ('best_effort', 'reliable'):
                raise ValueError('Invalid QoS override reliability')
            depth = policy.get('depth', cfg['sensor_qos.depth'])
            if type(depth) is not int or not 1 <= depth <= 10000:
                raise ValueError('Invalid QoS override depth')
        frames = json.loads(cfg['sensor_frames'])
        validate_aliases(json.loads(cfg['topic_aliases']))
        if not isinstance(frames, dict) or any(
            not isinstance(v, str) or not v for v in frames.values()
        ):
            raise ValueError('sensor_frames must map bus:hex-address to nonempty frame names')

    def _issue(self, message):
        now = time.monotonic()
        with self._state_lock:
            report = message != self._last_issue or now - self._last_issue_time >= 5
            self._last_issue, self._last_issue_time = str(message), now
        if report:
            self.get_logger().warning(str(message))

    def _session_state(self, ready, reason):
        if not ready:
            self._subscribed = False
            self._last_rx = None
        # The worker observes generation changes even when no measurements arrive.
        self.get_logger().info(reason)

    def _receive(self, data):
        # A board can still send a previous client's stream. Only forward sensor
        # packets after this node has acknowledged its own acquisition request.
        if self._stop.is_set() or not self._subscribed:
            return
        receipt = Receipt(time.monotonic(), self.get_clock().now().nanoseconds)
        self._last_rx = receipt.monotonic
        try:
            self._data.put_nowait((self.session.generation, data, receipt))
        except queue.Full:
            with self._state_lock:
                self._queue_drops += 1
            self._issue('Receive queue full; dropped devjson message')

    def _inventory_changed(self, devices):
        for device in devices:
            device['stale'] = device['age_s'] > self.config['stale_after_s']
        self.adapters.sync(devices)
        self.descriptor_services.sync(devices)
        self._inventory = devices
        self.inventory_pub.publish(String(data=json_text(devices)))
        metadata = {
            f'{d.key.bus}:{d.key.address}': {
                'type_ref': d.type_ref,
                'revision': d.revision,
                'metadata': d.metadata,
            }
            for d in self.pipeline.registry.devices.values()
            if d.metadata
        }
        text = json_text(
            {
                'firmware': self.session.firmware,
                'generation': self.session.generation,
                'devices': metadata,
            }
        )
        if text != self._metadata_text:
            self.metadata_pub.publish(String(data=text))
            self._metadata_text = text

    def _work(self):
        while not self._stop.is_set():
            generation = self.session.generation
            if generation != self._active_generation:
                self._active_generation = generation
                self.pipeline.reset()
                self.adapters.cache.clear()
            now = time.monotonic()
            if now >= self._next_inventory:
                self._inventory_changed(
                    self.pipeline.registry.snapshot(now, self.config['stale_after_s'])
                )
                self._next_inventory = now + 1.0
            try:
                job_generation, deadline, function, future = self._commands.get_nowait()
            except queue.Empty:
                pass
            else:
                if not future.set_running_or_notify_cancel():
                    continue
                if job_generation != generation or time.monotonic() > deadline:
                    future.set_exception(SessionError('Queued request expired or session changed'))
                    continue
                try:
                    future.set_result(function())
                except Exception as exc:
                    future.set_exception(exc)
                continue
            try:
                event_generation, data, receipt = self._data.get(timeout=0.05)
            except queue.Empty:
                continue
            # A new session may start while get() waits. Keep its first packet,
            # but discard queued packets belonging to previous sessions.
            generation = self.session.generation
            if event_generation != generation or not self._subscribed:
                continue
            if generation != self._active_generation:
                self._active_generation = generation
                self.pipeline.reset()
                self.adapters.cache.clear()
            try:
                self.raw_pub.publish(
                    String(
                        data=json_text(
                            {
                                'generation': generation,
                                'received_ns': receipt.ros_ns,
                                'payload': data,
                            }
                        )
                    )
                )
                self.pipeline.process(data, receipt, lambda: generation == self.session.generation)
                self._counts = dict(self.pipeline.counts)
            except Exception as exc:
                self._issue(f'Pipeline failure: {exc}')
        while True:
            try:
                _, _, _, future = self._commands.get_nowait()
                if not future.done():
                    future.set_exception(SessionError('Node shutting down'))
            except queue.Empty:
                break

    def _worker_call(self, function, timeout=5.0):
        future = Future()
        try:
            self._commands.put_nowait(
                (self.session.generation, time.monotonic() + timeout, function, future)
            )
        except queue.Full as exc:
            raise SessionError('Configuration queue full') from exc
        try:
            return future.result(timeout)
        except TimeoutError as exc:
            future.cancel()
            raise SessionError('Configuration request timed out') from exc

    def _connect(self, uri=None):
        if not self._connection_lock.acquire(blocking=False):
            raise SessionError('Connection already in progress')
        try:
            cfg = self.config
            target = uri or (
                cfg['serial.port'] if cfg['transport'] == 'serial' else cfg['device_uri']
            )
            self.session.connect(
                target,
                transport=cfg['transport'],
                ws_mode=cfg['ws_pcol'],
                serial_mode=cfg['serial.mode'],
                baud=cfg['serial.baud'],
                serial_timeout=cfg['serial.timeout'],
                timeout=cfg['rpc_default_timeout'],
            )
            if self._desired_rate > 0:
                self.session.subscribe(
                    self._desired_rate, cfg['publish_trigger'], cfg['rpc_default_timeout']
                )
                self._subscribed = True
            if uri:
                self.config['serial.port' if cfg['transport'] == 'serial' else 'device_uri'] = uri
        except Exception:
            self.session.close('Connection or subscription failed')
            raise
        finally:
            self._next_reconnect = time.monotonic() + self.config['reconnect_interval']
            self._connection_lock.release()

    def _maintain_connection(self):
        if self._stop.is_set():
            return
        if self._connect_task and self._connect_task.done():
            try:
                self._connect_task.result()
            except Exception as exc:
                self._issue(f'Connect failed: {exc}')
            self._connect_task = None
        if (
            self._desired_connection
            and not self.session.connected
            and not self.session.connecting
            and self._connect_task is None
            and time.monotonic() >= self._next_reconnect
        ):
            self._connect_task = self._connector.submit(self._connect)
            if not self.config['auto_reconnect']:
                self._desired_connection = False

    def handle_connect(self, request, response):
        self._desired_connection = self.config['auto_reconnect']
        try:
            if not self.config['autosub'] and not self.session.connected:
                # An explicit connection is a separate step from requesting data,
                # including after a previous subscribed session was disconnected.
                self._desired_rate = 0.0
            self._connect(request.device_uri or None)
            response.success, response.message = (
                True,
                'Firmware handshake acknowledged; '
                + ('acquisition subscribed' if self._subscribed else 'acquisition stopped'),
            )
        except Exception as exc:
            response.success, response.message = False, str(exc)
        return response

    def handle_disconnect(self, request, response):
        self._desired_connection = False
        self.session.close()
        response.success, response.message = True, 'Disconnected; automatic reconnect disabled'
        return response

    def handle_get_state(self, request, response):
        response.connected = self.session.connected
        response.device_uri = self.session.uri
        response.last_error = self.session.last_error if not self.session.connected else ''
        return response

    def _service(self, response, function):
        if not self._rpc_slots.acquire(blocking=False):
            response.success, response.message = False, 'RPC capacity busy; retry later'
            return response
        try:
            function()
            response.success, response.message = True, 'Acknowledged by firmware'
        except Exception as exc:
            response.success, response.message = False, str(exc)
        finally:
            self._rpc_slots.release()
        return response

    def handle_ping(self, request, response):
        return self._service(
            response,
            lambda: setattr(
                response,
                'rtt_ms',
                self.session.ping(request.payload_size, self.config['rpc_default_timeout']),
            ),
        )

    def handle_ric_rest_url(self, request, response):
        def run():
            if request.ws_pcol and request.ws_pcol != self.config['ws_pcol']:
                raise SessionError(
                    'Framing is fixed for the session; reconnect with ws_pcol configured'
                )
            result = self.session.request(
                request.url_path,
                request.timeout if request.timeout > 0 else self.config['rpc_default_timeout'],
            )
            response.json_text = json_text(result)
            if any(part in request.url_path for part in ('devconfig', 'devlib', 'reidentify')):
                self._worker_call(self.pipeline.reset)

        return self._service(response, run)

    def handle_subscription(self, request, response):
        def configure():
            self.session.subscribe(
                request.rate_hz, self.config['publish_trigger'], self.config['rpc_default_timeout']
            )
            self._desired_rate = request.rate_hz
            self._subscribed = request.rate_hz > 0
            # Run on the decode worker so a successful stop response also means
            # no earlier packet is still being decoded or waiting in the queue.
            while True:
                try:
                    self._data.get_nowait()
                except queue.Empty:
                    break

        return self._service(response, lambda: self._worker_call(configure))

    def handle_sample_rate(self, request, response):
        def configure():
            key = DeviceKey(request.bus, format(int(request.address, 16), 'x'))
            result = self.pipeline.configure_rate(key, request.sample_rate_hz)
            # Discard packets queued across a rate transition; interpreting them
            # with the new period would fabricate sample timing.
            self._discard_data()
            return result

        def run():
            result = self._worker_call(configure)
            response.sample_rate_hz = float(result['sampleRateHz'])
            response.poll_interval_us = int(result['pollIntervalUs'])
            response.retained_poll_results = int(result['numSamples'])

        return self._service(response, run)

    def _discard_data(self):
        while True:
            try:
                self._data.get_nowait()
                self._queue_drops += 1
            except queue.Empty:
                break

    def _diagnostics(self):
        now = time.monotonic()
        status = DiagnosticStatus()
        status.name = self.get_fully_qualified_name() + '/firmware_session'
        status.hardware_id = self.session.uri
        status.level = DiagnosticStatus.OK
        status.message = 'Connected' if self.session.connected else 'Disconnected'
        if self._desired_connection and not self.session.connected:
            status.level = DiagnosticStatus.ERROR
            status.message = self.session.last_error or 'Connecting'
        elif self._last_issue and now - self._last_issue_time < 10:
            status.level = DiagnosticStatus.WARN
            status.message = self._last_issue
        elif self._subscribed and (
            self._last_rx is None or now - self._last_rx > self.config['stale_after_s']
        ):
            status.level = DiagnosticStatus.WARN
            status.message = 'No recent firmware publications'
        values = dict(
            self._counts,
            receive_queue_drops=self._queue_drops,
            subscribed=self._subscribed,
            generation=self.session.generation,
            rx_age_s=None if self._last_rx is None else now - self._last_rx,
            upstream_policy='single acquisition owner; other firmware clients may consume samples',
            timestamp_policy='estimated acquisition time; not MCU clock synchronization',
        )
        status.values = [KeyValue(key=k, value=str(v)) for k, v in values.items()]
        msg = DiagnosticArray()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.status = [status]
        self.diagnostic_pub.publish(msg)

    def destroy_node(self):
        self._desired_connection = False
        self._stop.set()
        self.session.close('Node shutting down')
        self._worker.join(timeout=5)
        self._connector.shutdown(wait=True, cancel_futures=True)
        self.adapters.cache.clear()
        self.descriptor_services.clear()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = None
    executor = MultiThreadedExecutor(num_threads=4)
    try:
        node = AxiomBridgeNode()
        executor.add_node(node)
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        if node:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
