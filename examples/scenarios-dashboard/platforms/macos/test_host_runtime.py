"""A failed ROS acknowledgment must not strand owned containers and relays."""

import json
import subprocess
from types import SimpleNamespace
from unittest.mock import Mock, patch

import demo
import pytest


def test_stop_continues_cleanup_after_ros_pre_stop_timeout(tmp_path):
    def run(args, **kwargs):
        if args[:2] == ["docker", "exec"]:
            raise subprocess.TimeoutExpired(args, 15)
        return Mock(returncode=0, stdout="")

    with (
        patch("demo.STATE", tmp_path),
        patch("demo.owned_container", return_value=True),
        patch("demo.subprocess.run", side_effect=run) as commands,
        patch("demo.stop_controller"),
    ):
        demo.stop()
    calls = [call.args[0] for call in commands.call_args_list]
    assert ["docker", "kill", "--signal=SIGINT", demo.NAME] in calls
    assert ["docker", "stop", "-t", "15", demo.NAME] in calls
    assert ["docker", "rm", demo.NAME] in calls


def test_multiple_boards_have_separate_names_and_relays():
    args = SimpleNamespace(axiom=['front=/dev/cu.front', 'rear=/dev/cu.rear'], axiom_port=None)
    assert demo.axiom_connections(args) == [
        ('axiom/front', 8765, '/dev/cu.front'), ('axiom/rear', 8766, '/dev/cu.rear')]
    args.axiom = ['front=/dev/cu.same', 'rear=/dev/cu.same']
    with pytest.raises(ValueError, match='different USB port'):
        demo.axiom_connections(args)
    args.axiom = ['front=/dev/cu.front', 'front=/dev/cu.rear']
    with pytest.raises(ValueError, match='unique'):
        demo.axiom_connections(args)


def test_machine_profile_uses_container_paths_and_external_config(tmp_path, monkeypatch):
    config = tmp_path / 'machine with spaces.env'
    config.write_text(
        'ROS_WORKSPACE=/workspace\nROS_DOMAIN_ID=57\nAXIOM_DASHBOARD_PORT=8085\n'
        'AXIOM_ROS_BOARDS_FILE="$AXIOM_ROS_ROOT/config/boards.yaml"\n'
    )
    monkeypatch.setenv('AXIOM_MACHINE_CONFIG', str(config))
    machine, mounts = demo.machine_environment()
    assert machine['ROS_WORKSPACE'] == '/workspace'
    assert machine['ROS_DOMAIN_ID'] == '57'
    assert machine['AXIOM_DASHBOARD_PORT'] == '8085'
    assert machine['AXIOM_ROS_BOARDS_FILE'] == '/axiom/config/boards.yaml'
    assert machine['AXIOM_MACHINE_CONFIG'] == '/machine.env'
    assert mounts == ['-v', f'{config}:/machine.env:ro']


def test_cli_only_machine_keeps_empty_board_file_for_generated_fallback(tmp_path, monkeypatch):
    monkeypatch.delenv('AXIOM_MACHINE_CONFIG', raising=False)
    monkeypatch.setattr(demo, 'AXIOM', tmp_path)
    machine, mounts = demo.machine_environment()
    assert machine['AXIOM_ROS_BOARDS_FILE'] == ''
    assert machine['ROS_WORKSPACE'] == '/ws'
    assert machine['ROS_DOMAIN_ID'] == '43'
    assert mounts == []


def test_start_shares_profile_with_guide_consoles_and_reset(tmp_path, monkeypatch):
    repo, state = tmp_path / 'repo', tmp_path / 'runtime'
    (repo / 'config').mkdir(parents=True)
    config = repo / 'config/machine.env'
    config.write_text('ROS_WORKSPACE=/workspace\nROS_DOMAIN_ID=57\nAXIOM_DASHBOARD_PORT=8085\n')
    boards = repo / 'config/boards.yaml'
    contents = 'axioms:\n  axiom:\n    device_uri: ws://192.168.1.3/ws\n'
    boards.write_text(contents)
    monkeypatch.delenv('AXIOM_MACHINE_CONFIG', raising=False)
    monkeypatch.setattr(demo, 'AXIOM', repo)
    monkeypatch.setattr(demo, 'STATE', state)
    args = SimpleNamespace(axiom=[], axiom_port=None, with_dashboard=True,
                           marty_ip='192.168.1.8', demo='learning')
    with (
        patch('demo.owned_container', return_value=False),
        patch('demo.available') as available,
        patch('demo.run') as commands,
        patch('demo.relay', return_value={'pid': 123}),
        patch('demo.os.kill'), patch('demo.time.sleep'), patch('demo.start_controller'),
    ):
        demo.start(args)
    assert boards.read_text() == contents
    assert not (state / 'ws/axioms.yaml').exists()
    command = commands.call_args.args
    assert 'ROS_DOMAIN_ID=57' in command and 'AXIOM_ROS_BOARDS_FILE=/axiom/config/boards.yaml' in command
    assert '127.0.0.1:8085:8085' in command
    assert f'{config}:/machine.env:ro' in command
    assert f'{state / "ws"}:/workspace' in command
    assert any('source /axiom/scripts/setup_env.sh\n' in arg for arg in command)
    assert 'dashboard_port:=8085' in command
    available.assert_any_call(8085)
    assert json.loads((state / 'demo.json').read_text())['dashboard_port'] == 8085
