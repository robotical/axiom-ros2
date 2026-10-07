"""Desktop availability and shutdown are independent of application windows."""

import io
import json
import signal
import subprocess
from unittest.mock import Mock, patch

from desktop_runtime import DesktopRuntime


def test_shutdown_cleans_remaining_children_when_process_group_disappears(tmp_path):
    with patch.object(DesktopRuntime, 'publish'):
        runtime = DesktopRuntime()
    runtime.status = tmp_path / 'status.json'
    first, second = Mock(pid=101), Mock(pid=102)
    first.poll.return_value = second.poll.return_value = None
    second.wait.side_effect = [subprocess.TimeoutExpired('rviz', 3), 0]
    runtime.children = [('display', first), ('rviz', second)]
    logs = [io.StringIO(), io.StringIO()]
    runtime.logs = logs
    with patch('desktop_runtime.os.killpg', side_effect=ProcessLookupError) as kill:
        runtime.close()
    assert kill.call_args_list[-1].args == (102, signal.SIGKILL)
    assert first.wait.called and second.wait.call_count == 2
    assert all(log.closed for log in logs)
    assert '"available": false' in runtime.status.read_text()


def test_closing_apps_keeps_desktop_available_but_service_failure_does_not(tmp_path):
    with patch.object(DesktopRuntime, 'publish'):
        runtime = DesktopRuntime()
    runtime.status = tmp_path / 'status.json'
    runtime.error = ''
    runtime.children = [(name, Mock(poll=Mock(return_value=None)))
                        for name in runtime.services]
    runtime.children += [('rviz', Mock(poll=Mock(return_value=0))),
                         ('terminal', Mock(poll=Mock(return_value=0))),
                         ('dashboard', Mock(poll=Mock(return_value=0)))]
    runtime.publish()
    assert json.loads(runtime.status.read_text())['available']
    runtime.children[0][1].poll.return_value = 1
    runtime.publish()
    status = json.loads(runtime.status.read_text())
    assert not status['available']
    assert runtime.children[0][0] in status['error']
