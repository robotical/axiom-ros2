"""USB waiting, background verification and shutdown without physical ports."""

from concurrent.futures import Future, ThreadPoolExecutor
from importlib import import_module, metadata
import threading
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
    serial_open = Mock(side_effect=AssertionError('Tests must not open physical serial ports'))
    monkeypatch.setattr(serial, 'Serial', serial_open)
    module = import_module('axiom_driver.usb_discovery_node')
    monkeypatch.setattr(module, 'probe_axiom_firmware', Mock(return_value={
        'rslt': 'ok', 'SystemName': 'Axiom018',
    }))
    yield module
    serial_open.assert_not_called()


@pytest.fixture
def probe_pool(discovery_module, monkeypatch):
    jobs = []
    pool = Mock(spec=['submit', 'shutdown'])

    def submit(function, *args, **kwargs):
        future = Future()
        jobs.append(SimpleNamespace(future=future, function=function, args=args, kwargs=kwargs))
        return future

    def shutdown(wait=True, cancel_futures=False):
        if cancel_futures:
            for job in jobs:
                job.future.cancel()

    pool.submit.side_effect = submit
    pool.shutdown.side_effect = shutdown
    factory = Mock(return_value=pool)
    monkeypatch.setattr(discovery_module, 'ThreadPoolExecutor', factory)
    return SimpleNamespace(pool=pool, jobs=jobs, factory=factory)


@pytest.fixture
def make_node(discovery_module, probe_pool, monkeypatch):
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

    def close(node):
        if node in nodes:
            nodes.remove(node)
            executor.remove_node(node)
            return node.destroy_node()

    create.close = close
    try:
        yield create
    finally:
        for node in list(nodes):
            close(node)
        executor.shutdown(timeout_sec=1.0)
        if context.ok():
            context.shutdown()


def port(path, vid=None, pid=None):
    return SimpleNamespace(device=path, vid=vid, pid=pid)


def test_no_boards_scans_immediately_and_keeps_waiting_quietly(make_node, probe_pool):
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
    probe_pool.pool.submit.assert_not_called()


def test_unrelated_serial_ports_still_produce_waiting_state(make_node, probe_pool):
    provider = Mock(return_value=[
        port('/virtual/non-usb'),
        port('/virtual/other-vendor', vid=0x1234, pid=0x1001),
        port('/virtual/other-product', vid=0x303A, pid=0x9999),
    ])
    node, logger, _, _ = make_node(provider)
    node._scan()

    logger.info.assert_called_once_with('Waiting for an Axiom...')
    logger.warning.assert_not_called()
    probe_pool.pool.submit.assert_not_called()


def test_candidate_order_changes_do_not_repeat_status_or_submit_duplicate_jobs(
    make_node, probe_pool,
):
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
    assert probe_pool.pool.submit.call_count == 2
    assert all(job.future.cancelled() for job in probe_pool.jobs)


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


def test_successful_probe_is_reported_once_and_not_resubmitted(make_node, probe_pool):
    candidate = port('/virtual/axiom', vid=0x303A, pid=0x1001)
    node, logger, _, _ = make_node(Mock(return_value=[candidate]))
    future = probe_pool.jobs[0].future

    node._scan()
    assert not future.done()
    assert logger.info.call_count == 1
    future.set_result({'rslt': 'ok', 'SystemName': 'Axiom018'})
    node._scan()
    node._scan()

    assert probe_pool.pool.submit.call_count == 1
    assert logger.info.call_count == 2
    logger.info.assert_called_with('Axiom verified: /virtual/axiom (Axiom018)')
    logger.warning.assert_not_called()


@pytest.mark.parametrize('failed', [False, True], ids=['unrecognised', 'failed'])
def test_rejected_or_failed_probe_is_reported_once_without_stopping_node(
    make_node, probe_pool, failed,
):
    candidate = port('/virtual/other', vid=0x303A, pid=0x1001)
    node, logger, _, context = make_node(Mock(return_value=[candidate]))
    future = probe_pool.jobs[0].future
    if failed:
        future.set_exception(RuntimeError('Port busy'))
    else:
        future.set_result(None)

    node._scan()
    node._scan()

    assert context.ok()
    assert probe_pool.pool.submit.call_count == 1
    if failed:
        logger.warning.assert_called_once_with('USB probe failed for /virtual/other: Port busy')
        assert logger.info.call_count == 1
    else:
        logger.info.assert_called_with('USB candidate not recognised: /virtual/other')
        assert logger.info.call_count == 2
        logger.warning.assert_not_called()


def test_multiple_candidates_get_independent_jobs_and_results(
    discovery_module, make_node, probe_pool,
):
    first = port('/virtual/first', vid=0x303A, pid=0x1001)
    second = port('/virtual/second', vid=0x303A, pid=0x1001)
    node, logger, _, _ = make_node(Mock(return_value=[second, first]))

    probe_pool.factory.assert_called_once_with(
        max_workers=1, thread_name_prefix='axiom-usb-probe',
    )
    assert [job.args for job in probe_pool.jobs] == [('/virtual/first',), ('/virtual/second',)]
    assert all(job.function is discovery_module.probe_axiom_firmware for job in probe_pool.jobs)
    node._scan()
    assert probe_pool.pool.submit.call_count == 2

    probe_pool.jobs[0].future.set_exception(RuntimeError('First probe failed'))
    probe_pool.jobs[1].future.set_result({'rslt': 'ok', 'SystemName': 'Axiom018'})
    node._scan()
    node._scan()

    logger.warning.assert_called_once_with(
        'USB probe failed for /virtual/first: First probe failed',
    )
    logger.info.assert_called_with('Axiom verified: /virtual/second (Axiom018)')
    assert probe_pool.pool.submit.call_count == 2


def test_queued_probe_is_cancelled_on_removal(make_node, probe_pool):
    candidate = port('/virtual/axiom', vid=0x303A, pid=0x1001)
    provider = Mock(return_value=[candidate])
    node, logger, _, _ = make_node(provider)
    future = probe_pool.jobs[0].future

    provider.return_value = []
    node._scan()
    node._scan()

    assert future.cancelled()
    logger.info.assert_called_with('Waiting for an Axiom...')
    logger.warning.assert_not_called()


def test_completed_candidate_is_probed_again_after_replug(make_node, probe_pool):
    candidate = port('/virtual/axiom', vid=0x303A, pid=0x1001)
    provider = Mock(return_value=[candidate])
    node, logger, _, _ = make_node(provider)
    probe_pool.jobs[0].future.set_result({'rslt': 'ok', 'SystemName': 'Axiom009'})
    node._scan()

    provider.return_value = []
    node._scan()
    provider.return_value = [candidate]
    node._scan()
    assert probe_pool.pool.submit.call_count == 2
    probe_pool.jobs[1].future.set_result({'rslt': 'ok', 'SystemName': 'Axiom018'})
    node._scan()
    node._scan()

    logger.info.assert_called_with('Axiom verified: /virtual/axiom (Axiom018)')
    assert probe_pool.pool.submit.call_count == 2


def test_late_result_from_removed_board_is_discarded_when_path_is_reused(make_node, probe_pool):
    candidate = port('/virtual/axiom', vid=0x303A, pid=0x1001)
    provider = Mock(return_value=[candidate])
    node, logger, _, _ = make_node(provider)
    old_future = probe_pool.jobs[0].future
    assert old_future.set_running_or_notify_cancel()

    provider.return_value = []
    node._scan()
    provider.return_value = [candidate]
    node._scan()
    old_future.set_result({'rslt': 'ok', 'SystemName': 'Axiom009'})
    node._scan()

    assert all('Axiom verified:' not in call.args[0] for call in logger.info.call_args_list)
    probe_pool.jobs[1].future.set_result({'rslt': 'ok', 'SystemName': 'Axiom018'})
    node._scan()

    logger.info.assert_called_with('Axiom verified: /virtual/axiom (Axiom018)')
    assert all('Axiom009' not in call.args[0] for call in logger.info.call_args_list)
    assert probe_pool.pool.submit.call_count == 2


def test_enumeration_error_preserves_pending_probe_until_inventory_recovers(make_node, probe_pool):
    candidate = port('/virtual/axiom', vid=0x303A, pid=0x1001)
    provider = Mock(return_value=[candidate])
    node, logger, _, _ = make_node(provider)
    future = probe_pool.jobs[0].future
    future.set_result({'rslt': 'ok', 'SystemName': 'Axiom018'})

    provider.side_effect = OSError('Temporary enumeration failure')
    node._scan()
    assert logger.info.call_count == 1
    provider.side_effect = None
    node._scan()
    node._scan()

    logger.info.assert_any_call('Axiom verified: /virtual/axiom (Axiom018)')
    logger.warning.assert_called_once_with('USB enumeration failed: Temporary enumeration failure')
    assert probe_pool.pool.submit.call_count == 1


def test_running_probe_leaves_ros_callbacks_responsive_and_logs_on_ros_thread(
    discovery_module, make_node, monkeypatch,
):
    started = threading.Event()
    release = threading.Event()
    worker_threads = []
    log_threads = []
    owner_thread = threading.get_ident()

    def probe(path):
        worker_threads.append(threading.get_ident())
        started.set()
        if not release.wait(5):
            raise RuntimeError('Test did not release the probe')
        return {'rslt': 'ok', 'SystemName': 'Axiom018'}

    monkeypatch.setattr(discovery_module, 'ThreadPoolExecutor', ThreadPoolExecutor)
    monkeypatch.setattr(discovery_module, 'probe_axiom_firmware', probe)
    candidate = port('/virtual/axiom', vid=0x303A, pid=0x1001)
    try:
        node, logger, executor, _ = make_node(Mock(return_value=[candidate]))
        logger.info.side_effect = lambda message: log_threads.append(threading.get_ident())
        assert started.wait(1)
        future = node._probe_futures[candidate.device]

        heartbeat = threading.Event()
        node.create_timer(0.01, heartbeat.set)
        deadline = time.monotonic() + 1.0
        while not heartbeat.is_set() and time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.05)

        assert heartbeat.is_set(), 'The pending probe blocked other ROS callbacks'
        assert not future.done()
        assert len(worker_threads) == 1
        assert worker_threads[0] != owner_thread
        node._scan()
        assert logger.info.call_count == 1

        release.set()
        future.result(timeout=1)
        node._scan()
        logger.info.assert_called_with('Axiom verified: /virtual/axiom (Axiom018)')
        assert log_threads == [owner_thread]
    finally:
        release.set()


def test_shutdown_waits_for_active_probe_and_cancels_queued_probe(
    discovery_module, make_node, monkeypatch,
):
    started = threading.Event()
    release = threading.Event()
    closed = threading.Event()
    calls = []
    errors = []

    def probe(path):
        calls.append(path)
        started.set()
        if not release.wait(5):
            raise RuntimeError('Test did not release the probe')
        return {'rslt': 'ok', 'SystemName': 'Axiom018'}

    monkeypatch.setattr(discovery_module, 'ThreadPoolExecutor', ThreadPoolExecutor)
    monkeypatch.setattr(discovery_module, 'probe_axiom_firmware', probe)
    first = port('/virtual/first', vid=0x303A, pid=0x1001)
    second = port('/virtual/second', vid=0x303A, pid=0x1001)
    node, _, _, _ = make_node(Mock(return_value=[first, second]))
    queued = node._probe_futures[second.device]

    def close():
        try:
            make_node.close(node)
        except Exception as exc:
            errors.append(exc)
        finally:
            closed.set()

    closer = threading.Thread(target=close)
    try:
        assert started.wait(1)
        closer.start()
        deadline = time.monotonic() + 1.0
        while not queued.cancelled() and time.monotonic() < deadline:
            time.sleep(0.01)

        assert queued.cancelled()
        assert node._timer.is_canceled()
        assert not closed.is_set(), 'Shutdown returned while its probe was still running'
    finally:
        release.set()
        if closer.ident is not None:
            closer.join(timeout=2)

    assert closed.is_set() and not closer.is_alive()
    assert not errors
    assert calls == ['/virtual/first']


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
