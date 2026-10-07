"""Shutdown during desktop startup must not start the ROS graph afterward."""

import signal
from unittest.mock import Mock, patch

from container_demo import main


def test_shutdown_during_desktop_startup_skips_ros_launch():
    handlers = {}
    viewer = Mock()
    viewer.start.side_effect = lambda: handlers[signal.SIGTERM](signal.SIGTERM, None)
    with patch('container_demo.sys.argv', ['container_demo.py']), \
            patch('container_demo.DesktopRuntime', return_value=viewer), \
            patch('container_demo.signal.signal', side_effect=handlers.__setitem__), \
            patch('container_demo.subprocess.Popen') as launch:
        assert main() == 128 + signal.SIGTERM
    launch.assert_not_called()
    viewer.close.assert_called_once()


def test_learning_desktop_without_guide_never_launches_ros():
    handlers = {}
    viewer = Mock()
    viewer.publish.side_effect = lambda: handlers[signal.SIGTERM](signal.SIGTERM, None)
    with patch('container_demo.sys.argv', ['container_demo.py']), \
            patch('container_demo.DesktopRuntime', return_value=viewer) as desktop, \
            patch('container_demo.signal.signal', side_effect=handlers.__setitem__), \
            patch('container_demo.time.sleep'), \
            patch('container_demo.subprocess.Popen') as launch:
        assert main() == 128 + signal.SIGTERM
    desktop.assert_called_once_with(0, auto_apps=False)
    launch.assert_not_called()
    viewer.close.assert_called_once()


def test_learning_with_guide_starts_only_read_only_observer():
    handlers = {}
    viewer, observer = Mock(), Mock()
    observer.poll.return_value = None
    observer.wait.return_value = 0
    viewer.publish.side_effect = lambda: handlers[signal.SIGTERM](signal.SIGTERM, None)
    with patch('container_demo.sys.argv', ['container_demo.py', '--with-dashboard']), \
            patch('container_demo.DesktopRuntime', return_value=viewer) as desktop, \
            patch('container_demo.signal.signal', side_effect=handlers.__setitem__), \
            patch('container_demo.time.sleep'), \
            patch('container_demo.subprocess.Popen', return_value=observer) as launch:
        assert main() == 128 + signal.SIGTERM
    desktop.assert_called_once_with(8083, auto_apps=False)
    assert launch.call_count == 1
    command = launch.call_args.args[0]
    assert command[:4] == ['ros2', 'run', 'axiom_marty_dashboard', 'dashboard']
    assert 'host:=0.0.0.0' in command and 'port:=8083' in command
    viewer.open_dashboard_when_ready.assert_called_once()
    observer.send_signal.assert_called_with(signal.SIGTERM)
    viewer.close.assert_called_once()


def test_stopping_optional_guide_keeps_learning_desktop_available():
    handlers = {}
    viewer, observer = Mock(), Mock()
    observer.poll.return_value = 0
    ticks = []

    def publish():
        ticks.append(True)
        if len(ticks) == 2:
            handlers[signal.SIGTERM](signal.SIGTERM, None)

    viewer.publish.side_effect = publish
    with patch('container_demo.sys.argv', ['container_demo.py', '--with-dashboard']), \
            patch('container_demo.DesktopRuntime', return_value=viewer), \
            patch('container_demo.signal.signal', side_effect=handlers.__setitem__), \
            patch('container_demo.time.sleep'), \
            patch('container_demo.subprocess.Popen', return_value=observer) as launch:
        assert main() == 128 + signal.SIGTERM
    assert len(ticks) == 2
    assert launch.call_count == 1  # No automatic restart of the optional guide.
    observer.send_signal.assert_not_called()
    viewer.close.assert_called_once()
