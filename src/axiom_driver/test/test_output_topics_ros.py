"""Direct output topics through real DDS, driver dispatch and firmware framing."""

import math
import threading
import time
from urllib.parse import parse_qs, urlsplit

import pytest

rclpy = pytest.importorskip('rclpy')
from axiom_driver.axiom_bridge_node import AxiomBridgeNode  # noqa: E402,I100
from axiom_interfaces.srv import (  # noqa: E402
    Connect, DeviceCommand, Disconnect, PublishedDataSubscription,
)
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402
from std_msgs.msg import ColorRGBA, Float64  # noqa: E402
from test_ros_integration import wait_until  # noqa: E402
from test_session import FirmwareServer  # noqa: E402


class OutputRig:
    """Run a driver with a servo and LED stick on a framed WebSocket firmware peer."""

    def __init__(self, catalogue, namespace='/output_test'):
        self.namespace = namespace
        self.peer = FirmwareServer()
        self.reject = False

        def reply(path, response):
            if isinstance(path, str) and path.startswith('devman/typeinfo'):
                servo = parse_qs(urlsplit(path).query).get('addr') == ['0x10']
                response.update(dtIdx=1 if servo else 2,
                                devinfo=catalogue['RoboticalServo' if servo else 'QwiicLEDStick'])
            elif isinstance(path, str) and path.startswith('devman/cmdraw') and self.reject:
                response.update(rslt='fail', error='Test output rejected')
            return response
        self.peer.callback = reply
        rclpy.init()
        self.driver = AxiomBridgeNode(
            namespace=namespace, use_global_arguments=False,
            parameter_overrides=[Parameter('auto_connect', value=False),
                                 Parameter('auto_reconnect', value=False),
                                 Parameter('autosub', value=False),
                                 Parameter('device_uri', value=self.peer.uri),
                                 Parameter('stale_after_s', value=10.0)])
        self.probe = Node('output_topic_probe', namespace=namespace, use_global_arguments=False)
        self.executor = SingleThreadedExecutor()
        for node in (self.driver, self.probe):
            self.executor.add_node(node)
        self.thread = threading.Thread(target=self.executor.spin, daemon=True)
        self.thread.start()
        self.angle_path = namespace + '/roboticalservo_b1_10/commands/angle'
        self.pixel_path = namespace + '/qwiicledstick_b1_20/commands/pixels/pixel_'
        self.angle = self.probe.create_publisher(Float64, self.angle_path, 1)
        self.pixels = [self.probe.create_publisher(ColorRGBA, self.pixel_path + str(i), 1)
                       for i in range(2)]

    def call(self, kind, name, **fields):
        """Await a real ROS service reply while the independent executor spins."""
        client = self.probe.create_client(kind, self.namespace + '/' + name)
        try:
            assert client.wait_for_service(timeout_sec=3)
            future = client.call_async(kind.Request(**fields))
            wait_until(future.done)
            assert future.result().success, future.result().message
            return future.result()
        finally:
            self.probe.destroy_client(client)

    def connect(self):
        """Discover the same two output devices in a new session."""
        self.call(Connect, 'connect', device_uri='')
        self.call(PublishedDataSubscription, 'publish_data_subscription', rate_hz=20.)
        self.publish()
        wait_until(lambda: self.angle.get_subscription_count() == 1
                   and all(pub.get_subscription_count() == 1 for pub in self.pixels))

    def publish(self, servo_online=1):
        """Keep device availability independent of target-topic publication."""
        self.peer.publish({'_v': 1, '1': {
            '10': {'_i': 1, '_o': servo_online, 'x': ''},
            '20': {'_i': 2, '_o': 1, 'x': ''}}})

    def writes(self):
        """Return the actual addressed wire writes received by mock firmware."""
        return [parse_qs(urlsplit(path).query) for path in self.peer.paths
                if path.startswith('devman/cmdraw')]

    def close(self, extra_nodes=()):
        """Stop all test processes and sockets without physical hardware."""
        self.executor.shutdown(timeout_sec=3)
        self.thread.join(3)
        for node in extra_nodes:
            node.destroy_node()
        self.driver.destroy_node()
        self.probe.destroy_node()
        rclpy.shutdown()
        self.peer.close()


@pytest.fixture
def outputs(catalogue):
    """Supply direct command topics backed by the real driver pipeline."""
    rig = OutputRig(catalogue)
    try:
        rig.connect()
        yield rig
    finally:
        rig.close()


def test_topics_replace_angle_and_pixel_services_and_encode_real_writes(outputs):
    """Expose standard message types, preserving only discrete operation services."""
    rig = outputs
    services = dict(rig.probe.get_service_names_and_types())
    assert rig.angle_path not in services
    assert rig.pixel_path.rsplit('/', 1)[0] not in services
    assert rig.angle_path.replace('angle', 'enable') in services
    servo = next(row for row in rig.driver._inventory if row['type'] == 'RoboticalServo')
    assert servo['command_topics'][0]['unit'] == 'rad'
    assert all(item['name'] != 'angle' for item in servo['commands'])
    rig.angle.publish(Float64(data=math.radians(-12.34)))
    rig.pixels[1].publish(ColorRGBA(r=1., g=0., b=0.5, a=1.))
    wait_until(lambda: len(rig.writes()) == 2)
    assert {'deviceid': ['1_10'], 'hexWr': ['0001ff850064']} in rig.writes()
    assert {'deviceid': ['1_20'], 'hexWr': ['7101ff0080']} in rig.writes()
    rig.angle.publish(Float64(data=math.nan))
    rig.pixels[0].publish(ColorRGBA(r=-1., g=0., b=0., a=1.))
    time.sleep(.2)
    assert len(rig.writes()) == 2
    rig.angle.publish(Float64(data=math.radians(181)))
    time.sleep(.2)
    assert len(rig.writes()) == 2
    assert rig.thread.is_alive()


def test_busy_driver_coalesces_targets_independently_for_each_pixel(outputs):
    """Avoid a target FIFO while retaining updates for different LED pixels."""
    rig = outputs
    original = rig.driver.pipeline.command
    entered, release = threading.Event(), threading.Event()

    def delayed(*args):
        if args[2] == 'angle' and not entered.is_set():
            entered.set()
            assert release.wait(3)
        return original(*args)
    rig.driver.pipeline.command = delayed
    try:
        rig.angle.publish(Float64(data=math.radians(10)))
        assert entered.wait(2)
        for value in (20, 30, 40):
            rig.angle.publish(Float64(data=math.radians(value)))
            wait_until(lambda: rig.driver.descriptor_commands.pending.get(
                rig.angle_path.removeprefix('/output_test/'), (None, None))[1] == [float(value)])
        rig.pixels[0].publish(ColorRGBA(r=1., g=0., b=0., a=1.))
        rig.pixels[1].publish(ColorRGBA(r=0., g=1., b=0., a=1.))
        rig.pixels[0].publish(ColorRGBA(r=0., g=0., b=1., a=1.))
        wait_until(lambda: len(rig.driver.descriptor_commands.pending) == 3)
        release.set()
        wait_until(lambda: len(rig.writes()) == 4)
        assert [item['hexWr'][0] for item in rig.writes() if item['deviceid'] == ['1_10']] == [
            '000100640064', '000101900064']
        colours = {item['hexWr'][0] for item in rig.writes() if item['deviceid'] == ['1_20']}
        assert colours == {'71000000ff', '710100ff00'}
    finally:
        release.set()


def test_rejected_target_reports_diagnostics_and_is_not_retried(outputs):
    """Keep the node alive after rejection and accept the next fresh target."""
    rig = outputs
    rig.reject = True
    rig.angle.publish(Float64(data=0.1))
    wait_until(lambda: 'command failed' in rig.driver._last_issue)
    assert len(rig.writes()) == 1
    time.sleep(.15)
    assert len(rig.writes()) == 1
    rig.reject = False
    rig.angle.publish(Float64(data=0.2))
    wait_until(lambda: len(rig.writes()) == 2)


def test_disconnect_and_device_removal_do_not_replay_previous_targets(outputs):
    """Retire inputs and cached targets across both device and transport lifetimes."""
    rig = outputs
    rig.angle.publish(Float64(data=0.1))
    wait_until(lambda: len(rig.writes()) == 1)
    rig.publish(servo_online=0)
    wait_until(lambda: rig.angle.get_subscription_count() == 0)
    rig.publish()
    wait_until(lambda: rig.angle.get_subscription_count() == 1)
    time.sleep(.15)
    assert len(rig.writes()) == 1
    rig.call(Disconnect, 'disconnect')
    wait_until(lambda: rig.angle.get_subscription_count() == 0)
    rig.connect()
    time.sleep(.15)
    assert len(rig.writes()) == 1
    rig.angle.publish(Float64(data=0.1))
    wait_until(lambda: len(rig.writes()) == 2)


def test_discrete_led_off_invalidates_the_previous_colour_cache(outputs):
    """Allow the same colour to be requested again after an acknowledged off."""
    rig = outputs
    colour = ColorRGBA(r=1., g=0., b=0., a=1.)
    rig.pixels[0].publish(colour)
    wait_until(lambda: len(rig.writes()) == 1)
    rig.call(DeviceCommand, 'qwiicledstick_b1_20/commands/off', values=[])
    rig.pixels[0].publish(colour)
    wait_until(lambda: len(rig.writes()) == 3)
    assert [item['hexWr'][0] for item in rig.writes()] == ['7100ff0000', '78', '7100ff0000']


def test_transient_publisher_does_not_replay_a_target_on_device_reappearance(outputs):
    """Volatile command inputs never request a publisher's retained old target."""
    from rclpy.qos import DurabilityPolicy, QoSProfile

    rig = outputs
    rig.publish(servo_online=0)
    wait_until(lambda: rig.angle.get_subscription_count() == 0)
    latched = rig.probe.create_publisher(
        Float64, rig.angle_path, QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL))
    latched.publish(Float64(data=0.1))
    rig.publish()
    wait_until(lambda: latched.get_subscription_count() == 1)
    time.sleep(.2)
    assert not rig.writes()
    latched.publish(Float64(data=0.2))
    wait_until(lambda: len(rig.writes()) == 1)
