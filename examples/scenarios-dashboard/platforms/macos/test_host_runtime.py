"""A failed ROS acknowledgment must not strand owned containers and relays."""

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
