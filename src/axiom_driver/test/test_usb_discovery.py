"""Discovery lifecycle with real ROS executors and controlled firmware probes."""

from concurrent.futures import Future, ThreadPoolExecutor
from importlib import import_module, metadata
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import call, Mock

import pytest

rclpy = pytest.importorskip('rclpy')
from rclpy.context import Context  # noqa: E402
from rclpy.executors import ExternalShutdownException, SingleThreadedExecutor  # noqa: E402
from rclpy.node import Node  # noqa: E402
from rclpy.parameter import Parameter  # noqa: E402

ID_A = '001122334455'
ID_B = 'aabbccddeeff'


def port(path, vid=0x303A, pid=0x1001):
    return SimpleNamespace(device=path, vid=vid, pid=pid)


def firmware(identity=ID_A):
    return {'rslt': 'ok', 'SystemName': 'Axiom018', 'MAC': identity}


@pytest.fixture
def module(monkeypatch):
    import serial

    serial_open = Mock(side_effect=AssertionError('No physical serial access in discovery tests'))
    monkeypatch.setattr(serial, 'Serial', serial_open)
    value = import_module('axiom_driver.discovery_node')
    monkeypatch.setattr(value, 'probe_axiom_firmware', Mock(return_value=firmware()))
    monkeypatch.setattr(value, 'probe_network_firmware', Mock(return_value=firmware()))
    yield value
    serial_open.assert_not_called()


@pytest.fixture
def pool(module, monkeypatch):
    jobs = []
    worker = Mock(spec=['submit', 'shutdown'])

    def submit(function, *args):
        future = Future()
        jobs.append(SimpleNamespace(future=future, function=function, args=args))
        return future

    def shutdown(wait=True, cancel_futures=False):
        if cancel_futures:
            for job in jobs:
                job.future.cancel()

    worker.submit.side_effect = submit
    worker.shutdown.side_effect = shutdown
    monkeypatch.setattr(module, 'ThreadPoolExecutor', Mock(return_value=worker))
    return SimpleNamespace(worker=worker, jobs=jobs)


@pytest.fixture
def create(module, pool, monkeypatch, tmp_path):
    context = Context()
    rclpy.init(args=[], context=context)
    executor = SingleThreadedExecutor(context=context)
    logger = Mock(spec=['info', 'warning'])
    clock = Mock(return_value=100.0)
    monkeypatch.setattr(module, 'monotonic', clock)
    monkeypatch.setattr(module.AxiomDiscoveryNode, 'get_logger', lambda self: logger)
    nodes, drivers = [], []

    def driver_factory(discovery, namespace, params):
        child = Node('axiom_bridge_node', namespace=namespace, context=context,
                     use_global_arguments=False)
        child.config = params
        child.session = SimpleNamespace(connected=False)
        child._desired_connection = params['auto_connect']
        child._desired_rate = params['publish_rate_hz'] if params['autosub'] else 0.0
        child._identity_changed = False
        child.destroy_node = Mock(wraps=child.destroy_node)
        drivers.append(child)
        return child

    constructor = Mock(side_effect=driver_factory)
    monkeypatch.setattr(module.AxiomDiscoveryNode, '_create_driver',
                        lambda self, namespace, params: constructor(self, namespace, params))

    def factory(ports=(), network=(), config=None, wifi=False):
        provider = Mock(return_value=list(ports))
        browser = Mock(spec=['snapshot', 'close'])
        browser.snapshot.return_value = tuple(network)
        filename = ''
        if config is not None:
            path = tmp_path / f'boards-{len(nodes)}.yaml'
            path.write_text(json.dumps(config))
            filename = str(path)
        node = module.AxiomDiscoveryNode(
            port_provider=provider, network_provider=browser, context=context,
            use_global_arguments=False, parameter_overrides=[
                Parameter('boards_file', value=filename), Parameter('wifi', value=wifi),
            ],
        )
        nodes.append(node)
        executor.add_node(node)
        return SimpleNamespace(node=node, ports=provider, network=browser, clock=clock,
                               executor=executor, context=context, logger=logger,
                               constructor=constructor, drivers=drivers)

    def close(node):
        if node in nodes:
            nodes.remove(node)
            executor.remove_node(node)
            node.destroy_node()

    factory.close = close
    try:
        yield factory
    finally:
        for node in list(nodes):
            close(node)
        executor.shutdown(timeout_sec=1.0)
        context.shutdown()


def test_zero_boards_waits_once_across_real_ros_timer_callbacks(create, pool):
    env = create()
    deadline = time.monotonic() + 7
    while env.ports.call_count < 3 and time.monotonic() < deadline:
        env.executor.spin_once(timeout_sec=0.1)
    assert env.ports.call_count >= 3
    env.logger.info.assert_called_once_with('Waiting for an Axiom...')
    env.logger.warning.assert_not_called()
    pool.worker.submit.assert_not_called()
    env.constructor.assert_not_called()


def test_nonmatching_ports_and_reordered_candidates_do_not_create_duplicate_jobs(create, pool):
    env = create([port('/virtual/b'), port('/virtual/a'), port('/other', vid=1)])
    assert [job.args for job in pool.jobs] == [('/virtual/a',), ('/virtual/b',)]
    env.ports.return_value.reverse()
    env.node._scan()
    assert env.logger.info.call_count == 1
    assert len(pool.jobs) == 2
    env.ports.return_value = []
    env.node._scan()
    env.node._scan()
    assert all(job.future.cancelled() for job in pool.jobs)
    env.logger.info.assert_called_with('Waiting for an Axiom...')


def test_verified_board_starts_once_with_automatic_parameters(create, pool):
    env = create([port('/virtual/a')])
    env.node._scan()
    env.constructor.assert_not_called()
    pool.jobs[0].future.set_result(firmware())
    env.node._scan()
    env.node._scan()
    assert len(env.drivers) == 1 and len(pool.jobs) == 1
    driver = env.node._drivers[ID_A][1]
    assert driver.context is env.context and driver in env.executor.get_nodes()
    assert driver.get_namespace() == '/axiom_' + ID_A
    assert driver.config['frame_id'] == 'axiom_' + ID_A
    assert driver.config['transport'] == 'serial'
    assert driver.config['serial.port'] == '/virtual/a'
    assert all(driver.config[name] for name in ('auto_connect', 'auto_reconnect', 'autosub'))
    assert driver._expected_identity == ID_A


@pytest.mark.parametrize('response', [None, firmware(''), firmware('invalid')])
def test_unrecognised_or_unidentifiable_board_is_not_started_or_retried(create, pool, response):
    env = create([port('/virtual/a')])
    pool.jobs[0].future.set_result(response)
    env.node._scan()
    env.clock.return_value = 1000
    env.node._scan()
    env.constructor.assert_not_called()
    assert len(pool.jobs) == 1
    assert env.logger.warning.call_count == 1


def test_exception_retries_after_delay_and_suppresses_identical_errors(create, pool):
    env = create([port('/virtual/a')])
    for index, error in enumerate(['busy', 'busy', 'timeout']):
        pool.jobs[index].future.set_exception(RuntimeError(error))
        env.node._scan()
        assert env.logger.warning.call_count == (1 if index < 2 else 2)
        env.clock.return_value += 4.99
        env.node._scan()
        assert len(pool.jobs) == index + 1
        env.clock.return_value += 0.01
        env.node._scan()
        assert len(pool.jobs) == index + 2
        env.node._scan()
        assert len(pool.jobs) == index + 2
    pool.jobs[-1].future.set_result(firmware())
    env.node._scan()
    assert ID_A in env.node._drivers


def test_retry_of_one_port_does_not_disturb_other_board(create, pool):
    env = create([port('/virtual/a'), port('/virtual/b')])
    pool.jobs[0].future.set_exception(RuntimeError('busy'))
    pool.jobs[1].future.set_result(firmware(ID_B))
    env.node._scan()
    second = env.node._drivers[ID_B][1]
    env.clock.return_value += 5
    env.node._scan()
    pool.jobs[2].future.set_result(firmware(ID_A))
    env.node._scan()
    assert set(env.node._drivers) == {ID_A, ID_B}
    assert env.node._drivers[ID_B][1] is second
    second.destroy_node.assert_not_called()


@pytest.mark.parametrize('next_path', ['/virtual/a', '/virtual/renumbered'])
def test_replug_keeps_identity_namespace_and_other_board_running(create, pool, next_path):
    env = create([port('/virtual/a'), port('/virtual/b')])
    for job, identity in zip(pool.jobs, (ID_A, ID_B)):
        job.future.set_result(firmware(identity))
    env.node._scan()
    first, second = (env.node._drivers[identity][1] for identity in (ID_A, ID_B))
    original_namespace = first.get_namespace()
    env.ports.return_value = [port('/virtual/b')]
    env.node._scan()
    first.destroy_node.assert_called_once_with()
    assert first not in env.executor.get_nodes()
    assert env.node._drivers[ID_B][1] is second
    env.ports.return_value.append(port(next_path))
    env.node._scan()
    assert ID_A not in env.node._drivers
    pool.jobs[2].future.set_result(firmware(ID_A))
    env.node._scan()
    replacement = env.node._drivers[ID_A][1]
    assert replacement is not first
    assert replacement.get_namespace() == original_namespace
    assert replacement.config['frame_id'] == first.config['frame_id']
    assert env.node._drivers[ID_B][1] is second
    second.destroy_node.assert_not_called()


@pytest.mark.parametrize('late_failure', [False, True])
def test_late_probe_is_discarded_after_path_removal_and_reuse(create, pool, late_failure):
    env = create([port('/virtual/a')])
    old = pool.jobs[0].future
    assert old.set_running_or_notify_cancel()
    env.ports.return_value = []
    env.node._scan()
    env.ports.return_value = [port('/virtual/a')]
    env.node._scan()
    if late_failure:
        old.set_exception(RuntimeError('stale failure'))
    else:
        old.set_result(firmware(ID_B))
    env.node._scan()
    assert not env.node._drivers
    pool.jobs[1].future.set_result(firmware(ID_A))
    env.node._scan()
    assert set(env.node._drivers) == {ID_A}
    env.logger.warning.assert_not_called()


def test_unplug_clears_retry_deadline_and_error_suppression(create, pool):
    env = create([port('/virtual/a')])
    pool.jobs[0].future.set_exception(RuntimeError('busy'))
    env.node._scan()
    env.ports.return_value = []
    env.node._scan()
    env.ports.return_value = [port('/virtual/a')]
    env.node._scan()
    assert len(pool.jobs) == 2
    pool.jobs[1].future.set_exception(RuntimeError('busy'))
    env.node._scan()
    assert env.logger.warning.call_count == 2


@pytest.mark.parametrize('completed', [False, True])
def test_enumeration_failure_preserves_pending_probe_or_managed_driver(create, pool, completed):
    env = create([port('/virtual/a')])
    if completed:
        pool.jobs[0].future.set_result(firmware())
        env.node._scan()
    env.ports.side_effect = OSError('temporary enumeration failure')
    env.node._scan()
    env.node._scan()
    assert len(pool.jobs) == 1
    assert not pool.jobs[0].future.cancelled()
    if completed:
        env.drivers[0].destroy_node.assert_not_called()
    env.logger.warning.assert_called_once_with(
        'USB enumeration failed: temporary enumeration failure')
    env.ports.side_effect = None
    if not completed:
        pool.jobs[0].future.set_result(firmware())
    env.node._scan()
    assert ID_A in env.node._drivers


def test_wifi_verification_uses_non_acquiring_probe_and_deduplicates_usb(create, pool, module):
    uri = 'ws://192.0.2.10/ws'
    env = create([port('/virtual/a')], [uri], wifi=True)
    assert pool.jobs[0].function is module.probe_axiom_firmware
    assert pool.jobs[1].function is module.probe_network_firmware
    for job in pool.jobs:
        job.future.set_result(firmware())
    env.node._scan()
    assert len(env.drivers) == 1
    assert env.node._drivers[ID_A][0] == ('serial', '/virtual/a')
    env.ports.return_value = []
    env.node._scan()
    assert env.node._drivers[ID_A][0] == ('ws', uri)
    assert len(env.drivers) == 2
    env.drivers[0].destroy_node.assert_called_once_with()


@pytest.mark.parametrize('disconnected', [False, True])
def test_wifi_to_usb_switch_preserves_manual_connection_and_acquisition_choice(
    create, pool, disconnected,
):
    env = create(network=['ws://192.0.2.10/ws'], wifi=True)
    pool.jobs[0].future.set_result(firmware())
    env.node._scan()
    original = env.drivers[0]
    original._desired_connection = not disconnected
    original._desired_rate = 0.0
    env.ports.return_value = [port('/virtual/a')]
    env.node._scan()
    pool.jobs[1].future.set_result(firmware())
    env.node._scan()
    replacement = env.node._drivers[ID_A][1]
    assert replacement is not original
    assert replacement._desired_connection is (not disconnected)
    assert replacement._desired_rate == 0.0
    original.destroy_node.assert_called_once_with()


def test_changed_physical_board_at_same_endpoint_requires_reverification(create, pool):
    env = create([port('/virtual/a')])
    pool.jobs[0].future.set_result(firmware())
    env.node._scan()
    original = env.drivers[0]
    original._identity_changed = True
    env.node._scan()
    assert not env.node._drivers
    original.destroy_node.assert_called_once_with()
    assert len(pool.jobs) == 2
    pool.jobs[1].future.set_result(firmware(ID_B))
    env.node._scan()
    assert set(env.node._drivers) == {ID_B}
    assert env.node._drivers[ID_B][1].get_namespace() == '/axiom_' + ID_B


def test_optional_identity_rules_apply_aliases_and_limit_robot_membership(create, pool):
    env = create([port('/virtual/a'), port('/virtual/b')], config={
        'discovery': {'include_unconfigured': False},
        'axioms': {'robot/front': {
            'id': ID_A, 'publish_rate_hz': 20,
            'topic_aliases': {'range': {'type': 'VL53L4CD', 'source': 'range'}},
        }},
    })
    for job, identity in zip(pool.jobs, (ID_A, ID_B)):
        job.future.set_result(firmware(identity))
    env.node._scan()
    assert set(env.node._drivers) == {ID_A}
    driver = env.drivers[0]
    assert driver.get_namespace() == '/robot/front'
    assert driver.config['frame_id'] == 'robot_front'
    assert driver.config['publish_rate_hz'] == 20.0
    assert json.loads(driver.config['topic_aliases'])['range']['source'] == 'range'


def test_explicit_wifi_endpoint_works_without_mdns_and_manual_flags_are_respected(create, pool):
    uri = 'ws://192.0.2.10/ws'
    env = create(config={'axioms': {'axiom': {
        'transport': 'ws', 'device_uri': uri,
        'auto_connect': False, 'auto_reconnect': False, 'autosub': False,
    }}})
    assert pool.jobs[0].args == (uri,)
    pool.jobs[0].future.set_result(firmware())
    env.node._scan()
    driver = env.drivers[0]
    assert driver.get_namespace() == '/axiom'
    assert not driver._desired_connection and driver._desired_rate == 0


def test_endpoint_rule_keeps_its_transport_restriction_when_usb_disappears(create, pool):
    env = create([port('/virtual/a')], ['ws://192.0.2.10/ws'], wifi=True, config={
        'axioms': {'front': {'transport': 'serial', 'serial.port': '/virtual/a'}},
    })
    for job in pool.jobs:
        job.future.set_result(firmware())
    env.node._scan()
    assert env.node._drivers[ID_A][1].get_namespace() == '/front'
    env.ports.return_value = []
    env.node._scan()
    assert not env.node._drivers, 'A serial-only board must not reappear as unconfigured Wi-Fi'


def test_ambiguous_rules_fail_closed_without_duplicate_nodes(create, pool):
    env = create([port('/virtual/a')], config={'axioms': {
        'front': {'id': ID_A},
        'rear': {'transport': 'serial', 'serial.port': '/virtual/a'},
    }})
    pool.jobs[0].future.set_result(firmware())
    env.node._scan()
    env.node._scan()
    env.constructor.assert_not_called()
    env.logger.warning.assert_called_once_with(
        f'Axiom {ID_A}: Multiple board entries match this physical Axiom')


def test_no_executor_does_not_construct_bridge(create):
    env = create()
    env.node.executor = None
    with pytest.raises(RuntimeError, match='must be added to an executor'):
        env.node._start_driver(ID_A, '/axiom', ('serial', '/virtual/a'), {})
    env.constructor.assert_not_called()


def test_registration_failure_releases_unowned_bridge(create, monkeypatch):
    env = create()
    monkeypatch.setattr(
        env.executor, 'add_node', Mock(side_effect=RuntimeError('executor failed')))
    params = {'auto_connect': True, 'autosub': True, 'publish_rate_hz': 10.0}
    with pytest.raises(RuntimeError, match='executor failed'):
        env.node._start_driver(ID_A, '/axiom', ('serial', '/virtual/a'), params)
    env.drivers[0].destroy_node.assert_called_once_with()
    assert not env.node._drivers


@pytest.mark.parametrize('stopped', [False, True])
def test_shutdown_releases_all_drivers_network_browser_and_probe_worker(create, pool, stopped):
    env = create([port('/virtual/a'), port('/virtual/b')], wifi=True)
    for job, identity in zip(pool.jobs, (ID_A, ID_B)):
        job.future.set_result(firmware(identity))
    env.node._scan()
    if stopped:
        env.executor.shutdown(timeout_sec=1)
    create.close(env.node)
    assert not env.node._drivers
    for driver in env.drivers:
        driver.destroy_node.assert_called_once_with()
        assert driver not in env.executor.get_nodes()
    env.network.close.assert_called_once_with()
    pool.worker.shutdown.assert_called_once_with(wait=True, cancel_futures=True)


def test_pending_probe_keeps_ros_timer_responsive(create, module, monkeypatch):
    started, release, heartbeat = threading.Event(), threading.Event(), threading.Event()

    def probe(path):
        started.set()
        assert release.wait(5)
        return firmware()

    monkeypatch.setattr(module, 'ThreadPoolExecutor', ThreadPoolExecutor)
    monkeypatch.setattr(module, 'probe_axiom_firmware', probe)
    try:
        env = create([port('/virtual/a')])
        assert started.wait(1)
        env.node.create_timer(0.01, heartbeat.set)
        deadline = time.monotonic() + 1
        while not heartbeat.is_set() and time.monotonic() < deadline:
            env.executor.spin_once(timeout_sec=0.05)
        assert heartbeat.is_set()
        assert not env.node._drivers
        release.set()
        env.node._probe_futures[('serial', '/virtual/a')].result(timeout=1)
        env.node._scan()
        assert ID_A in env.node._drivers
    finally:
        release.set()


def test_shutdown_waits_for_active_probe_and_cancels_queued_jobs(create, module, monkeypatch):
    started, release, closed = threading.Event(), threading.Event(), threading.Event()
    errors = []

    def probe(path):
        started.set()
        assert release.wait(5)
        return firmware()

    # Deliberately retain one worker to make a queued cancellation deterministic.
    monkeypatch.setattr(module, 'ThreadPoolExecutor', lambda **kwargs: ThreadPoolExecutor(1))
    monkeypatch.setattr(module, 'probe_axiom_firmware', probe)
    env = create([port('/virtual/a'), port('/virtual/b')])
    queued = env.node._probe_futures[('serial', '/virtual/b')]

    def close():
        try:
            create.close(env.node)
        except Exception as exc:
            errors.append(exc)
        finally:
            closed.set()

    thread = threading.Thread(target=close)
    try:
        assert started.wait(1)
        thread.start()
        deadline = time.monotonic() + 1
        while not queued.cancelled() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert queued.cancelled() and not closed.is_set()
    finally:
        release.set()
        thread.join(2)
    assert closed.is_set() and not errors


@pytest.mark.parametrize('signal', [None, KeyboardInterrupt(), ExternalShutdownException()])
def test_run_cleans_up_executor_before_node_and_context(module, monkeypatch, signal):
    node = Mock(spec=['destroy_node'])
    executor = Mock(spec=['add_node', 'spin', 'shutdown'])
    executor.spin.side_effect = signal
    lifecycle = Mock()
    initialise, shutdown = Mock(), Mock()
    for name, operation in [('init', initialise), ('executor', executor),
                            ('node', node), ('shutdown', shutdown)]:
        lifecycle.attach_mock(operation, name)
    monkeypatch.setattr(module, 'SingleThreadedExecutor', Mock(return_value=executor))
    monkeypatch.setattr(rclpy, 'init', initialise)
    monkeypatch.setattr(rclpy, 'ok', Mock(return_value=True))
    monkeypatch.setattr(rclpy, 'shutdown', shutdown)
    module.run(Mock(return_value=node), args=[])
    assert lifecycle.mock_calls == [call.init(args=[]), call.executor.add_node(node),
                                    call.executor.spin(), call.executor.shutdown(),
                                    call.node.destroy_node(), call.shutdown()]


def test_run_releases_context_if_node_construction_fails(module, monkeypatch):
    executor, shutdown = Mock(), Mock()
    monkeypatch.setattr(module, 'SingleThreadedExecutor', Mock(return_value=executor))
    monkeypatch.setattr(rclpy, 'init', Mock())
    monkeypatch.setattr(rclpy, 'ok', Mock(return_value=True))
    monkeypatch.setattr(rclpy, 'shutdown', shutdown)
    with pytest.raises(ValueError, match='bad config'):
        module.run(Mock(side_effect=ValueError('bad config')), args=[])
    executor.shutdown.assert_called_once_with()
    shutdown.assert_called_once_with()


def test_created_bridge_uses_own_context_and_ignores_discovery_cli_overrides(module, pool):
    context = Context()
    rclpy.init(context=context, args=[
        '--ros-args', '-r', '__ns:=/ignored',
        '-r', '__node:=ignored', '-p', 'auto_connect:=false',
    ])
    node = driver = None
    try:
        node = module.AxiomDiscoveryNode(
            port_provider=lambda: [], context=context, use_global_arguments=False,
            parameter_overrides=[Parameter('wifi', value=False),
                                 Parameter('boards_file', value='')],
        )
        params = module.board_parameters('/axiom_' + ID_A, {
            'transport': 'serial', 'serial.port': '/virtual/a',
        })
        driver = node._create_driver('/axiom_' + ID_A, params)
        assert driver.context is context
        assert driver.get_namespace() == '/axiom_' + ID_A
        assert driver.get_name() == 'axiom_bridge_node'
        assert driver.config['auto_connect'] and driver.config['autosub']
        assert driver.executor is None and not driver.session.connected
    finally:
        if driver is not None:
            driver.destroy_node()
        if node is not None:
            node.destroy_node()
        context.shutdown()


@pytest.mark.parametrize('name', ['axiom_discovery', 'axiom_usb_discovery'])
def test_installed_console_entry_points_are_loadable(name):
    entries = [item for item in metadata.distribution('axiom_driver').entry_points
               if item.group == 'console_scripts' and item.name == name]
    assert len(entries) == 1 and callable(entries[0].load())
