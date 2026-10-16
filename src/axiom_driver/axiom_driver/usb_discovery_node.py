"""Discover USB candidates while waiting for Axiom boards."""

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from serial.tools.list_ports import comports

USB_CANDIDATE_IDS = {(0X303A, 0X1001)}


class UsbDiscoveryNode(Node):

    def __init__(self, port_provider=None, **kwargs):
        super().__init__('axiom_usb_discovery', **kwargs)

        self._port_provider = (
            comports if port_provider is None else port_provider
        )
        self._last_status = None

        self._timer = self.create_timer(2.0, self._scan)
        self._scan()

    def _scan(self):
        try:
            candidates = tuple(sorted(
                port.device
                for port in self._port_provider()
                if (port.vid, port.pid) in USB_CANDIDATE_IDS
            ))
        except OSError as exc:
            status = ('error', str(exc))
            message = f'USB enumeration failed: {exc}'
            log = self.get_logger().warning
        else:
            status = ('candidates', candidates)
            message = (
                'Waiting for an Axiom...'
                if not candidates
                else 'USB candidates found: ' + ', '.join(candidates)
            )
            log = self.get_logger().info

        if status != self._last_status:
            self._last_status = status
            log(message)


def main(args=None):
    rclpy.init(args=args)
    node = None

    try:
        node = UsbDiscoveryNode()
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()
