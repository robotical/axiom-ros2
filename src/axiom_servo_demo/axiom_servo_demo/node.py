"""Adapt Marty-style joint slider messages to existing Axiom descriptor services."""

import json
import math
import time

from axiom_interfaces.srv import DeviceCommand
from rcl_interfaces.msg import ParameterDescriptor
import rclpy
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node
from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
from rclpy.task import Future
from sensor_msgs.msg import JointState
from std_msgs.msg import String
from std_srvs.srv import SetBool

from .control import command_value, joint_position, select_servo, TargetGate


class ServoAdapter(Node):
    """Bound output to one live device, one RPC and one replaceable target."""

    def __init__(self, **kwargs):
        super().__init__('servo_adapter', **kwargs)
        defaults = {
            'axiom_namespace': '/axiom', 'servo': '',
            'angle_command': 'angle', 'enable_command': 'enable',
            'command_unit': 'degrees', 'joint_name': 'servo_joint',
            'start_enabled': True,
            'lower_limit_deg': -90.0, 'upper_limit_deg': 90.0,
            'command_rate_hz': 10.0, 'request_timeout_s': 4.0,
            'inventory_timeout_s': 2.5, 'slider_timeout_s': 1.0,
        }
        for name, default in defaults.items():
            self.declare_parameter(name, default, ParameterDescriptor(read_only=True))
        self.config = {name: self.get_parameter(name).value for name in defaults}
        cfg = self.config
        self.board = '/' + cfg['axiom_namespace'].strip('/')
        self.lower, self.upper = map(math.radians, (
            cfg['lower_limit_deg'], cfg['upper_limit_deg']))
        if (cfg['command_unit'] not in ('degrees', 'radians')
                or not math.isfinite(self.lower) or not math.isfinite(self.upper)
                or self.lower >= self.upper):
            raise ValueError('Invalid angle limits or command_unit')
        for name in ('command_rate_hz', 'request_timeout_s', 'inventory_timeout_s',
                     'slider_timeout_s'):
            if not math.isfinite(cfg[name]) or cfg[name] <= 0:
                raise ValueError(f'{name} must be positive and finite')
        if cfg['command_rate_hz'] > 50:
            raise ValueError('command_rate_hz must not exceed 50')
        self.gate = TargetGate()
        self.startup_enable_pending = cfg['start_enabled']
        self.binding = self.angle_client = self.enable_client = self.feedback_sub = None
        self.rpc = self.control = None
        self.last_inventory = self.last_slider = self.last_send = None
        self.last_message = None
        retained = QoSProfile(depth=1, durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self.status_pub = self.create_publisher(String, 'status', retained)
        self.observed_pub = self.create_publisher(JointState, 'observed_joint_states', 10)
        self.create_subscription(String, self.board + '/devices', self.on_inventory, retained)
        self.create_subscription(JointState, 'joint_commands', self.on_slider, 1)
        self.create_service(SetBool, 'set_enabled', self.set_enabled,
                            callback_group=ReentrantCallbackGroup())
        self.create_timer(0.02, self.tick)
        self.report('Waiting for device inventory; output is disarmed')

    def report(self, message):
        """Publish retained selection/arming status and log only changes."""
        state = {
            'servo': self.binding.topic if self.binding else None,
            'armed': self.gate.armed, 'message': message,
            'command_unit': self.config['command_unit'],
        }
        signature = json.dumps(state)
        if signature != self.last_message:
            self.last_message = signature
            self.status_pub.publish(String(data=signature))
            self.get_logger().info(message)

    def on_inventory(self, message):
        """Follow live descriptors and invalidate commands on removal/replacement."""
        self.last_inventory = time.monotonic()
        try:
            rows = json.loads(message.data)
            if not isinstance(rows, list):
                raise ValueError('Device inventory must be a list')
            binding = select_servo(rows, self.config['servo'], self.config['angle_command'],
                                   self.config['enable_command'])
        except (ValueError, KeyError, TypeError, AttributeError) as error:
            self.unbind(str(error))
            return
        if binding == self.binding:
            return
        self.unbind('Device selection changed; output is disarmed')
        self.binding = binding
        self.angle_client = self.create_client(
            DeviceCommand, self.board + '/' + binding.angle_service)
        self.enable_client = self.create_client(
            DeviceCommand, self.board + '/' + binding.enable_service)
        qos = QoSProfile(depth=1, reliability=ReliabilityPolicy.BEST_EFFORT)
        self.feedback_sub = self.create_subscription(
            JointState, self.board + '/' + binding.topic + '/joint_states',
            lambda message: self.on_feedback(message, binding), qos)
        next_step = ('waiting for slider and service before startup enable'
                     if self.startup_enable_pending
                     else 'call set_enabled, then move the slider')
        self.report(f'Selected {binding.topic}; {next_step}')

    def unbind(self, reason):
        """Forget old targets and complete waiting calls before retiring clients."""
        if self.binding is not None:
            self.startup_enable_pending = False
        self.gate = TargetGate()
        if self.rpc:
            self.rpc['client'].remove_pending_request(self.rpc['future'])
            self.rpc['future'].cancel()
            self.rpc = None
        self.finish_control(False, reason)
        for client in (self.angle_client, self.enable_client):
            if client:
                self.destroy_client(client)
        if self.feedback_sub:
            self.destroy_subscription(self.feedback_sub)
        self.binding = self.angle_client = self.enable_client = self.feedback_sub = None
        self.last_slider = None
        self.report(reason)

    def on_slider(self, message):
        """Validate/quantize input without sending an RPC from the subscription."""
        if not self.binding:
            return
        try:
            position = joint_position(message.name, message.position, self.config['joint_name'])
            if position is None:
                return
            value = command_value(self.binding.angle, position, self.config['command_unit'],
                                  self.lower, self.upper)
        except (ValueError, TypeError, OverflowError) as error:
            self.gate.desired = None
            self.report(f'Rejected slider command: {error}')
            return
        self.last_slider = time.monotonic()
        self.gate.observe(value)

    def on_feedback(self, message, binding):
        """Rename single-joint reported feedback without substituting target angles."""
        if binding != self.binding or len(message.name) != 1 or len(message.position) != 1:
            return
        if not math.isfinite(message.position[0]):
            return
        observed = JointState(header=message.header, name=[self.config['joint_name']],
                              position=list(message.position))
        self.observed_pub.publish(observed)

    async def set_enabled(self, request, response):
        """Acknowledge firmware enable/disable; arm only after a successful enable."""
        self.startup_enable_pending = False
        if not request.data:
            self.gate.disarm()
        if self.control:
            if not request.data and self.control['enabled']:
                self.finish_control(False, 'Enable superseded by a disable request')
            else:
                response.success, response.message = False, 'An enable/disable request is pending'
                return response
        if not self.binding or not self.enable_client.service_is_ready():
            response.success, response.message = False, 'Selected servo service is unavailable'
            self.report(response.message)
            return response
        if request.data and (self.last_slider is None or time.monotonic() - self.last_slider
                             > self.config['slider_timeout_s']):
            response.success, response.message = False, 'Wait for valid joint slider messages'
            self.report(response.message)
            return response
        response.success, response.message = await self.begin_control(request.data)
        return response

    def begin_control(self, enabled):
        """Queue startup or manual control through the same acknowledged request path."""
        self.startup_enable_pending = False
        self.gate.disarm()
        completion = Future()
        self.control = {'enabled': enabled, 'completion': completion}
        self.report('Waiting for firmware enable' if enabled else 'Waiting for firmware disable')
        return completion

    def finish_control(self, success, message):
        """Wake an asynchronous SetBool caller once a firmware result is known."""
        if self.control:
            completion = self.control['completion']
            self.control = None
            if not completion.done():
                completion.set_result((success, message))

    def send(self, client, values, kind):
        """Start one request; the timer handles completion and a bounded timeout."""
        try:
            future = client.call_async(DeviceCommand.Request(values=values))
        except Exception as error:
            self.gate.disarm()
            self.finish_control(False, str(error))
            self.report(f'Service request failed; output disarmed: {error}')
            return False
        self.rpc = {'client': client, 'future': future, 'kind': kind,
                    'control': self.control if kind == 'enable' else None,
                    'deadline': time.monotonic() + self.config['request_timeout_s']}
        return True

    def tick(self):
        """Process one RPC at a time and discard stale or superseded targets."""
        now = time.monotonic()
        if self.binding and now - self.last_inventory > self.config['inventory_timeout_s']:
            self.unbind('Device inventory expired; output is disarmed')
        if self.rpc:
            rpc, result, error = self.rpc, None, None
            if rpc['future'].done():
                try:
                    result = rpc['future'].result()
                except Exception as exception:
                    error = str(exception)
            elif now >= rpc['deadline']:
                rpc['client'].remove_pending_request(rpc['future'])
                rpc['future'].cancel()
                error = 'Firmware request timed out'
            else:
                return
            self.rpc = None
            if result is None or not result.success:
                reason = error or (result.message if result else 'Service returned no result')
                self.gate.disarm()
                if rpc['kind'] == 'enable' and rpc['control'] is self.control:
                    self.finish_control(False, reason)
                self.report(f'{reason}; output is disarmed')
            elif rpc['kind'] == 'enable' and rpc['control'] is self.control:
                if self.control['enabled']:
                    self.gate.arm()
                    message = 'Servo enabled; move the slider to send an angle'
                else:
                    message = 'Servo disabled'
                self.finish_control(True, message)
                self.report(message)
            elif rpc['kind'] == 'angle' and self.gate.armed:
                self.report('Angle commands active; acknowledgement is not motion completion')
        if not self.binding:
            return
        if (self.startup_enable_pending and self.last_slider is not None
                and now - self.last_slider <= self.config['slider_timeout_s']
                and self.enable_client.service_is_ready()):
            self.begin_control(True)
        if self.control:
            if not self.enable_client.service_is_ready():
                self.finish_control(False, 'Enable service is unavailable')
                self.report('Enable service is unavailable; output is disarmed')
            else:
                self.send(self.enable_client, [float(self.control['enabled'])], 'enable')
            return
        if self.gate.armed and (self.last_slider is None or now - self.last_slider
                                > self.config['slider_timeout_s']):
            self.gate.disarm()
            self.report('Joint slider messages expired; output is disarmed')
        target = self.gate.next_target()
        if target is None or (self.last_send is not None and now - self.last_send
                              < 1.0 / self.config['command_rate_hz']):
            return
        if not self.angle_client.service_is_ready():
            self.gate.disarm()
            self.report('Angle service is unavailable; output is disarmed')
        elif self.send(self.angle_client, [target], 'angle'):
            self.gate.sent(target)
            self.last_send = now


def main(args=None):
    """Run the adapter without starting another firmware acquisition connection."""
    rclpy.init(args=args)
    node = None
    try:
        node = ServoAdapter()
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        if node:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
