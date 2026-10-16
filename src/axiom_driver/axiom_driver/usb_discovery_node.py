"""Discover USB candidates while waiting for Axiom boards."""

from concurrent.futures import ThreadPoolExecutor
from time import monotonic

import rclpy
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from serial.tools.list_ports import comports

from .core.discovery import probe_axiom_firmware

USB_CANDIDATE_IDS = {(0X303A, 0X1001)}
PROBE_RETRY_DELAY_S = 5.0


class UsbDiscoveryNode(Node):

    def __init__(self, port_provider=None, **kwargs):
        super().__init__('axiom_usb_discovery', **kwargs)

        self._port_provider = (
            comports if port_provider is None else port_provider
        )
        self._last_status = None

        self._probe_executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix='axiom-usb-probe'
        )
        self._probe_futures = {}
        self._checked_ports = set()
        self._probe_retries = {}  # Port -> (retry deadline, last error message).

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
            self._update_probes(candidates)

        if status != self._last_status:
            self._last_status = status
            log(message)

    def _update_probes(self, candidates):
        """Schedule candidate probes and collect completed results."""
        current = set(candidates)

        self._checked_ports.intersection_update(current)
        for port in set(self._probe_retries) - current:
            del self._probe_retries[port]

        missing = set(self._probe_futures) - current
        for port in missing:
            future = self._probe_futures.pop(port)
            future.cancel()

        pending = list(self._probe_futures.items())
        for port, future in pending:
            if not future.done():
                continue

            del self._probe_futures[port]

            try:
                firmware = future.result()
            except Exception as exc:
                message = f'USB probe failed for {port}: {exc}'
                previous = self._probe_retries.get(port)
                if previous is None or previous[1] != message:
                    self.get_logger().warning(message)
                self._probe_retries[port] = (monotonic() + PROBE_RETRY_DELAY_S, message)
                continue

            self._checked_ports.add(port)
            self._probe_retries.pop(port, None)
            if firmware is None:
                message = f'USB candidate not recognised: {port}'
            else:
                name = firmware['SystemName']
                message = f'Axiom verified: {port} ({name})'

            self.get_logger().info(message)

        for port in sorted(current):
            if port in self._checked_ports or port in self._probe_futures:
                continue
            retry = self._probe_retries.get(port)
            if retry is not None and monotonic() < retry[0]:
                continue

            self._probe_futures[port] = self._probe_executor.submit(
                probe_axiom_firmware,
                port,
            )

    def destroy_node(self):
        """Stop scanning and release the probe worker."""
        self._timer.cancel()
        self._probe_executor.shutdown(
            wait=True,
            cancel_futures=True,
        )
        return super().destroy_node()


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
