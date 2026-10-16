"""USB waiting, scan transitions and shutdown without opening physical ports."""

from importlib import import_module, metadata
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

rclpy = pytest.importorskip('rclpy')
from rclpy.context import Context  # noqa: E402
from rclpy.executors import (  # noqa: E402
    ExternalShutdownException,
    SingleThreadedExecutor,
)


@pytest.fixture
def discovery_module(monkeypatch):
    import serial

    # Even an accidental serial open must fail before touching hardware.
    serial_open = Mock(side_effect=AssertionError('Discovery must not open a serial port'))
    monkeypatch.setattr(serial, 'Serial', serial_open)
    module = import_module('axiom_driver.usb_discovery_node')
    yield module
    serial_open.assert_not_called()


@pytest.fixture
def make_node(discovery_module, monkeypatch):
    context = Context()
    rclpy.init(args=[], context=context)
    executor = SingleThreadedExecutor(context=context)
    logger = Mock(spec=['info', 'warning'])
    monkeypatch.setattr(discovery_module.UsbDiscoveryNode, 'get_logger', lambda self: logger)
    nodes = []

    def create(provider=None):
        node = discovery_module.UsbDiscoveryNode(
            port_provider=provider, context=context, use_global_arguments=False,
        )
        nodes.append(node)
        executor.add_node(node)
        return node, logger, executor, context

    try:
        yield create
    finally:
        for node in nodes:
            executor.remove_node(node)
            node.destroy_node()
        executor.shutdown(timeout_sec=1.0)
        if context.ok():
            context.shutdown()


def port(path, vid=None, pid=None):
    return SimpleNamespace(device=path, vid=vid, pid=pid)


def test_no_boards_scans_immediately_and_keeps_waiting_quietly(make_node):
    provider = Mock(return_value=[])
    node, logger, executor, context = make_node(provider)

    provider.assert_called_once_with()
    logger.info.assert_called_once_with('Waiting for an Axiom...')

    # Exercise two real ROS timer callbacks, rather than only calling _scan.
    deadline = time.monotonic() + 8.0
    while provider.call_count < 3 and time.monotonic() < deadline:
        executor.spin_once(timeout_sec=0.1)

    assert provider.call_count >= 3, 'USB scanning stopped after the initial empty result'
    assert context.ok() and node.get_name() == 'axiom_usb_discovery'
    logger.info.assert_called_once_with('Waiting for an Axiom...')
    logger.warning.assert_not_called()


def test_unrelated_serial_ports_still_produce_waiting_state(make_node):
    provider = Mock(return_value=[
        port('/virtual/non-usb'),
        port('/virtual/other-vendor', vid=0x1234, pid=0x1001),
        port('/virtual/other-product', vid=0x303A, pid=0x9999),
    ])
    node, logger, _, _ = make_node(provider)
    node._scan()

    logger.info.assert_called_once_with('Waiting for an Axiom...')
    logger.warning.assert_not_called()


def test_candidates_are_only_reported_and_order_changes_do_not_repeat_logs(make_node):
    first = port('/virtual/first', vid=0x303A, pid=0x1001)
    second = port('/virtual/second', vid=0x303A, pid=0x1001)
    provider = Mock(return_value=[second, first])
    node, logger, _, _ = make_node(provider)

    logger.info.assert_called_once_with(
        'USB candidates found: /virtual/first, /virtual/second',
    )
    provider.return_value = [first, second]
    node._scan()
    assert logger.info.call_count == 1

    provider.return_value = []
    node._scan()
    node._scan()
    assert logger.info.call_count == 2
    logger.info.assert_called_with('Waiting for an Axiom...')
    logger.warning.assert_not_called()


def test_enumeration_error_is_reported_once_and_waiting_recovers(make_node):
    provider = Mock(return_value=[])
    node, logger, _, context = make_node(provider)
    provider.side_effect = OSError('temporary enumeration failure')
    node._scan()
    node._scan()

    logger.warning.assert_called_once_with(
        'USB enumeration failed: temporary enumeration failure',
    )
    provider.side_effect = None
    node._scan()
    node._scan()

    assert context.ok()
    assert logger.info.call_count == 2
    logger.info.assert_called_with('Waiting for an Axiom...')
    assert logger.warning.call_count == 1


def test_default_enumerator_is_used_when_no_provider_is_supplied(
    discovery_module, make_node, monkeypatch,
):
    provider = Mock(return_value=[])
    monkeypatch.setattr(discovery_module, 'comports', provider)
    _, logger, _, _ = make_node()

    provider.assert_called_once_with()
    logger.info.assert_called_once_with('Waiting for an Axiom...')


@pytest.mark.parametrize('shutdown_signal', [
    None, KeyboardInterrupt(), ExternalShutdownException(),
], ids=['spin-returns', 'ctrl-c', 'external-shutdown'])
def test_main_releases_node_and_ros_context(discovery_module, monkeypatch, shutdown_signal):
    node = Mock(spec=['destroy_node'])
    factory = Mock(return_value=node)
    initialise = Mock()
    spin = Mock(side_effect=shutdown_signal)
    shutdown = Mock()
    monkeypatch.setattr(discovery_module, 'UsbDiscoveryNode', factory)
    monkeypatch.setattr(rclpy, 'init', initialise)
    monkeypatch.setattr(rclpy, 'spin', spin)
    monkeypatch.setattr(rclpy, 'ok', Mock(return_value=True))
    monkeypatch.setattr(rclpy, 'shutdown', shutdown)

    discovery_module.main(args=[])

    initialise.assert_called_once_with(args=[])
    spin.assert_called_once_with(node)
    node.destroy_node.assert_called_once_with()
    shutdown.assert_called_once_with()


def test_main_shuts_down_ros_if_node_construction_fails(discovery_module, monkeypatch):
    factory = Mock(side_effect=RuntimeError('node construction failed'))
    shutdown = Mock()
    spin = Mock()
    monkeypatch.setattr(discovery_module, 'UsbDiscoveryNode', factory)
    monkeypatch.setattr(rclpy, 'init', Mock())
    monkeypatch.setattr(rclpy, 'spin', spin)
    monkeypatch.setattr(rclpy, 'ok', Mock(return_value=True))
    monkeypatch.setattr(rclpy, 'shutdown', shutdown)

    with pytest.raises(RuntimeError, match='node construction failed'):
        discovery_module.main(args=[])

    spin.assert_not_called()
    shutdown.assert_called_once_with()


def test_main_does_not_shutdown_an_already_stopped_context(discovery_module, monkeypatch):
    node = Mock(spec=['destroy_node'])
    shutdown = Mock()
    monkeypatch.setattr(discovery_module, 'UsbDiscoveryNode', Mock(return_value=node))
    monkeypatch.setattr(rclpy, 'init', Mock())
    monkeypatch.setattr(rclpy, 'spin', Mock(side_effect=ExternalShutdownException()))
    monkeypatch.setattr(rclpy, 'ok', Mock(return_value=False))
    monkeypatch.setattr(rclpy, 'shutdown', shutdown)

    discovery_module.main(args=[])

    node.destroy_node.assert_called_once_with()
    shutdown.assert_not_called()


def test_installed_usb_console_entry_point_is_loadable(discovery_module):
    distribution = metadata.distribution('axiom_driver')
    entries = [entry for entry in distribution.entry_points
               if entry.group == 'console_scripts' and entry.name == 'axiom_usb_discovery']

    assert len(entries) == 1, 'The installed package must expose axiom_usb_discovery'
    assert entries[0].load() is discovery_module.main
