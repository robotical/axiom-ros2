"""Real DDS angle topics and acknowledged enable calls; no hardware."""

import copy
import json
import math
import time

import pytest

rclpy = pytest.importorskip('rclpy')
from axiom_interfaces.srv import DeviceCommand  # noqa: E402,I100
from axiom_servo_demo.node import ServoAdapter  # noqa: E402
from rclpy.callback_groups import ReentrantCallbackGroup  # noqa: E402
from rclpy.executors import SingleThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402
from rclpy.qos import DurabilityPolicy, QoSProfile  # noqa: E402
from rclpy.task import Future  # noqa: E402
from sensor_msgs.msg import JointState  # noqa: E402
from std_msgs.msg import Float64, String  # noqa: E402
from std_srvs.srv import SetBool  # noqa: E402


class Rig:
    """Run the real adapter against angle-topic and enable-service peers."""

    def __init__(self, device, *, start_enabled=None, slider_live=True):
        rclpy.init()
        self.peer = Node('servo_test_peer', use_global_arguments=False)
        overrides = [
            Parameter('axiom_namespace', value='/servo_test_board'),
            Parameter('inventory_timeout_s', value=0.6),
            Parameter('slider_timeout_s', value=0.6),
            Parameter('request_timeout_s', value=0.8),
        ]
        if start_enabled is not None:
            overrides.append(Parameter('start_enabled', value=start_enabled))
        self.adapter = ServoAdapter(
            namespace='/servo_test_demo', use_global_arguments=False,
            parameter_overrides=overrides)
        self.executor = SingleThreadedExecutor()
        self.executor.add_node(self.peer)
        self.executor.add_node(self.adapter)
        self.rows = [copy.deepcopy(device)]
        self.position = 0.0
        self.inventory_live, self.slider_live = True, slider_live
        self.angle_targets, self.enable_calls, self.observed = [], [], []
        self.hold_enable = None
        self.fail_enable = False
        retained = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.inventory = self.peer.create_publisher(String, '/servo_test_board/devices', retained)
        self.slider = self.peer.create_publisher(
            JointState, '/servo_test_demo/joint_commands', 1)
        self.feedback = self.peer.create_publisher(
            JointState, '/servo_test_board/' + device['topic'] + '/joint_states', 10)
        self.peer.create_subscription(
            JointState, '/servo_test_demo/observed_joint_states', self.observed.append, 10)
        group = ReentrantCallbackGroup()
        self.services = {}
        self.angle_subscription = self.peer.create_subscription(
            Float64, '/servo_test_board/' + device['topic'] + '/commands/angle',
            lambda message: self.angle_targets.append(message.data), 1)
        for kind, callback in (('enable', self.enable),):
            path = '/servo_test_board/' + device['topic'] + '/commands/' + kind
            self.services[kind] = self.peer.create_service(
                DeviceCommand, path, callback, callback_group=group)
        self.peer.create_timer(0.05, self.publish)
        self.enabled = self.peer.create_client(SetBool, '/servo_test_demo/set_enabled')
        self.wait(lambda: self.adapter.binding is not None)
        if slider_live:
            self.wait(lambda: self.adapter.gate.latest == 0.)

    def publish(self):
        """Keep the inventory and slider alive independently."""
        if self.inventory_live:
            self.inventory.publish(String(data=json.dumps(self.rows)))
        if self.slider_live:
            self.slider.publish(JointState(name=['servo_joint'], position=[self.position]))

    async def enable(self, request, response):
        """Record both enable and disable writes."""
        self.enable_calls.append(list(request.values))
        if self.hold_enable:
            await self.hold_enable
        response.success = not self.fail_enable
        response.message = 'Enable rejected by test firmware' if self.fail_enable else 'ok'
        return response

    def wait(self, predicate, timeout=4):
        """Spin the executor until an observable state is reached."""
        deadline = time.monotonic() + timeout
        while not predicate() and time.monotonic() < deadline:
            self.executor.spin_once(timeout_sec=0.01)
        assert predicate(), self.adapter.last_message

    def spin(self, duration=0.15):
        """Let periodic input and replies settle without relying on thread sleeps."""
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            self.executor.spin_once(timeout_sec=0.01)

    def set_enabled(self, value):
        """Await the public SetBool acknowledgement."""
        future = self.enabled.call_async(SetBool.Request(data=value))
        self.wait(future.done)
        return future.result()

    def close(self):
        """Release pending callbacks and the ROS context."""
        self.inventory_live = self.slider_live = False
        for future in (self.hold_enable,):
            if future is not None and not future.done():
                future.set_result(None)
        self.spin(0.05)
        self.executor.shutdown()
        self.adapter.unbind('Test finished')
        self.adapter.destroy_node()
        self.peer.destroy_node()
        rclpy.shutdown()


@pytest.fixture
def rig(device):
    """Supply an isolated real ROS graph for each control scenario."""
    rig = Rig(device, start_enabled=False)
    try:
        yield rig
    finally:
        rig.close()


@pytest.fixture
def auto_rig(device):
    """Use the real startup default while withholding slider input initially."""
    rig = Rig(device, slider_live=False)
    try:
        yield rig
    finally:
        rig.close()


def test_default_startup_waits_for_input_service_and_acknowledgement(auto_rig, device):
    """Enable once after readiness, using the initial nonzero angle only as a baseline."""
    rig = auto_rig
    rig.spin()
    assert not rig.enable_calls and not rig.angle_targets
    rig.peer.destroy_service(rig.services['enable'])
    rig.wait(lambda: not rig.adapter.enable_client.service_is_ready())
    rig.position, rig.slider_live = math.radians(20), True
    rig.spin()
    assert not rig.enable_calls
    rig.hold_enable = Future()
    rig.services['enable'] = rig.peer.create_service(
        DeviceCommand, '/servo_test_board/' + device['topic'] + '/commands/enable',
        rig.enable, callback_group=ReentrantCallbackGroup())
    rig.wait(lambda: rig.enable_calls == [[1.0]])
    assert not rig.adapter.gate.armed and not rig.angle_targets
    rig.position = math.radians(22)
    rig.wait(lambda: rig.adapter.gate.latest == math.radians(22))
    rig.hold_enable.set_result(None)
    rig.hold_enable = None
    rig.wait(lambda: rig.adapter.gate.armed)
    rig.spin()
    assert not rig.angle_targets and rig.enable_calls == [[1.0]]
    rig.position = math.radians(25)
    rig.wait(lambda: rig.angle_targets == [math.radians(25)])


@pytest.mark.parametrize('failure', ['rejected', 'timeout'])
def test_startup_failure_is_not_retried_and_manual_enable_recovers(auto_rig, failure):
    """Keep failures disarmed, including late replies after an enable timeout."""
    rig = auto_rig
    if failure == 'rejected':
        rig.fail_enable = True
    else:
        rig.hold_enable = Future()
    rig.slider_live = True
    rig.wait(lambda: rig.enable_calls == [[1.0]] and rig.adapter.control is None)
    if rig.hold_enable is not None:
        rig.hold_enable.set_result(None)
        rig.hold_enable = None
    rig.fail_enable = False
    rig.position = 0.2
    rig.spin()
    assert not rig.adapter.gate.armed and not rig.angle_targets
    assert rig.enable_calls == [[1.0]]
    assert rig.set_enabled(True).success
    assert rig.adapter.gate.armed and not rig.angle_targets


@pytest.mark.parametrize('inflight', [False, True])
def test_explicit_disable_cancels_startup_enable(auto_rig, inflight):
    """Honor disable both before startup readiness and during its firmware request."""
    rig = auto_rig
    if inflight:
        rig.hold_enable = Future()
        rig.slider_live = True
        rig.wait(lambda: rig.enable_calls == [[1.0]])
    disable = rig.enabled.call_async(SetBool.Request(data=False))
    rig.wait(lambda: rig.adapter.control is not None and not rig.adapter.control['enabled'])
    if rig.hold_enable is not None:
        rig.hold_enable.set_result(None)
        rig.hold_enable = None
    rig.wait(disable.done)
    assert disable.result().success
    rig.position, rig.slider_live = 0.2, True
    rig.spin()
    assert rig.enable_calls == ([[1.0], [0.0]] if inflight else [[0.0]])
    assert not rig.adapter.gate.armed and not rig.angle_targets


@pytest.mark.parametrize('enabled_before_loss', [False, True])
def test_device_loss_consumes_startup_enable_even_before_readiness(auto_rig, enabled_before_loss):
    """Never enable a replacement automatically after the first selection is lost."""
    rig = auto_rig
    if enabled_before_loss:
        rig.slider_live = True
        rig.wait(lambda: rig.adapter.gate.armed)
    rows, rig.rows = rig.rows, []
    rig.wait(lambda: rig.adapter.binding is None)
    rig.rows, rig.slider_live = rows, True
    rig.wait(lambda: rig.adapter.binding is not None)
    rig.position = 0.2
    rig.spin()
    assert rig.enable_calls == ([[1.0]] if enabled_before_loss else [])
    assert not rig.adapter.gate.armed and not rig.angle_targets


def test_enable_changed_target_disable_and_separate_feedback(rig):
    """Starting/enabling does not move; slider angles never become feedback."""
    assert not rig.angle_targets and not rig.enable_calls and not rig.observed
    assert rig.set_enabled(True).success
    rig.spin()
    assert rig.enable_calls == [[1.0]] and not rig.angle_targets
    rig.position = math.radians(-12.34)
    rig.wait(lambda: len(rig.angle_targets) == 1)
    assert rig.angle_targets == [math.radians(-12.34)]
    rig.spin()
    assert len(rig.angle_targets) == 1 and not rig.observed
    rig.feedback.publish(JointState(name=['firmware_joint'], position=[0.5]))
    rig.wait(lambda: bool(rig.observed))
    assert rig.observed[-1].name == ['servo_joint']
    assert list(rig.observed[-1].position) == [0.5]
    assert rig.set_enabled(False).success
    rig.position = 0.3
    rig.spin()
    assert rig.enable_calls == [[1.0], [0.0]] and len(rig.angle_targets) == 1


def test_replacement_invalidates_inflight_requests_and_requires_explicit_reenable(rig):
    """A reply from a previous device revision cannot rearm its replacement."""
    rig.hold_enable = Future()
    future = rig.enabled.call_async(SetBool.Request(data=True))
    rig.wait(lambda: rig.enable_calls == [[1.0]])
    rig.rows[0]['revision'] += 1
    rig.wait(future.done)
    assert not future.result().success and not rig.adapter.gate.armed
    rig.hold_enable.set_result(None)
    rig.hold_enable = None
    rig.position = math.radians(30)
    rig.spin()
    assert not rig.angle_targets and not rig.adapter.gate.armed
    assert rig.set_enabled(True).success
    rig.spin()
    assert not rig.angle_targets
    rig.position = math.radians(31)
    rig.wait(lambda: rig.angle_targets == [math.radians(31)])


def test_disable_supersedes_a_pending_enable(rig):
    """A late enable reply cannot arm after the user requests disable."""
    rig.hold_enable = Future()
    enable = rig.enabled.call_async(SetBool.Request(data=True))
    rig.wait(lambda: rig.enable_calls == [[1.0]])
    disable = rig.enabled.call_async(SetBool.Request(data=False))
    rig.wait(enable.done)
    assert not enable.result().success
    rig.hold_enable.set_result(None)
    rig.hold_enable = None
    rig.wait(disable.done)
    assert disable.result().success
    assert rig.enable_calls == [[1.0], [0.0]] and not rig.adapter.gate.armed
    rig.position = 0.5
    rig.spin()
    assert not rig.angle_targets


def test_inventory_and_slider_expiry_do_not_rearm_automatically(rig):
    """Losing either the board inventory or the control stream drops targets."""
    assert rig.set_enabled(True).success
    rig.slider_live = False
    rig.wait(lambda: not rig.adapter.gate.armed)
    rig.slider_live = True
    rig.spin()
    assert not rig.adapter.gate.armed
    assert rig.set_enabled(True).success
    rig.inventory_live = False
    rig.wait(lambda: rig.adapter.binding is None)
    rig.inventory_live = True
    rig.wait(lambda: rig.adapter.binding is not None)
    assert not rig.adapter.gate.armed and not rig.angle_targets


def test_demo_limits_reject_targets_without_publishing(rig):
    """Keep the GUI-specific limits while the driver handles descriptor encoding."""
    assert rig.set_enabled(True).success
    rig.position = math.radians(100)
    rig.spin()
    assert not rig.angle_targets
    rig.position = math.radians(15)
    rig.wait(lambda: rig.angle_targets == [math.radians(15)])
