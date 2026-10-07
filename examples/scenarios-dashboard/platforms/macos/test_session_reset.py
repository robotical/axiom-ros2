"""Restart must refuse unrelated containers and bundled demos before stopping any process."""

import json
import io
from unittest.mock import Mock, patch

import pytest

from session_reset import restart


def test_reset_refuses_bundled_session_without_docker_operations(tmp_path):
    (tmp_path / ".runtime").mkdir()
    (tmp_path / ".runtime/demo.json").write_text(json.dumps({"demo": "sensors"}))
    with patch("session_reset.subprocess.run") as docker:
        with pytest.raises(RuntimeError, match="only in the manual learning"):
            restart(tmp_path)
    docker.assert_not_called()


def test_reset_refuses_container_without_project_ownership(tmp_path):
    (tmp_path / ".runtime").mkdir()
    (tmp_path / ".runtime/demo.json").write_text(json.dumps({"demo": "learning"}))
    with patch("session_reset.subprocess.run", return_value=Mock(stdout="false")) as docker:
        with pytest.raises(RuntimeError, match="not owned"):
            restart(tmp_path)
    assert docker.call_count == 1
    assert docker.call_args.args[0][:2] == ["docker", "inspect"]


def test_restart_uses_owned_container_id_even_if_name_is_reassigned(tmp_path):
    (tmp_path / ".runtime").mkdir()
    (tmp_path / ".runtime/demo.json").write_text(json.dumps({"demo": "learning"}))
    identity = "a" * 64
    response = io.BytesIO(json.dumps({"commands": [{}], "graph": {"available": True}}).encode())
    result = Mock(stdout="true|" + identity)
    with (
        patch("session_reset.subprocess.run", return_value=result) as docker,
        patch("session_reset.urlopen", return_value=response),
    ):
        restart(tmp_path)
    commands = [call.args[0] for call in docker.call_args_list]
    assert commands[1][:3] == ["docker", "exec", identity]
    assert commands[2][-1] == identity
