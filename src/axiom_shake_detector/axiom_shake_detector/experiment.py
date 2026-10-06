"""Own the teaching demo's ROS processes, recordings and exclusive input source."""

from datetime import datetime
import json
from pathlib import Path
import signal
import subprocess
import threading
import time

import yaml


class Experiments:
    """Run a fixed set of local ROS commands; never execute browser-supplied code."""

    def __init__(self, root, topic, driver_args, reset_view, live=True):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.topic, self.driver_args, self.reset_view = topic, driver_args, reset_view
        self.processes = {}
        self.logs = {}
        self.source = 'live' if live else 'recorded'
        self.bag = None
        self.busy = False
        self.notice = (
            'Move Axiom to publish your first measurements.'
            if live
            else 'Choose a recording or play the synthetic sample.'
        )
        self.error = ''
        self.recording = None
        self.record_until = None
        self.latest_recording = None
        self.record_result = None
        self.last_imu = None
        self.lock = threading.Lock()
        self.closed = threading.Event()
        self.start_detector()
        if live:
            self.start(
                'driver', ['ros2', 'run', 'axiom_driver', 'axiom_bridge_node', *driver_args]
            )
        self.monitor = threading.Thread(target=self.watch, daemon=True)
        self.monitor.start()

    def start(self, name, command):
        if self.running(name):
            return
        if name in self.processes:
            self.stop(name)
        log = (self.root / f'.{name}.log').open('a')
        try:
            process = subprocess.Popen(
                command,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except Exception:
            log.close()
            raise
        self.logs[name] = log
        self.processes[name] = process

    def stop(self, name):
        process = self.processes.pop(name, None)
        if process and process.poll() is None:
            # Stop the ros2 CLI and its executable together, allowing bag metadata to flush.
            try:
                import os

                os.killpg(process.pid, signal.SIGINT)
                process.wait(timeout=8)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=3)
            except ProcessLookupError:
                pass
        log = self.logs.pop(name, None)
        if log:
            log.close()

    def running(self, name):
        process = self.processes.get(name)
        return process is not None and process.poll() is None

    def start_detector(self, strict=False):
        name = 'strict' if strict else 'detector'
        args = [
            '--ros-args',
            '-r',
            '__ns:=/axiom',
            '-p',
            f'imu_topic:={self.topic}',
            '-p',
            'dashboard_port:=0',
        ]
        if strict:
            args += [
                '-r',
                '__node:=strict_detector',
                '-r',
                'shake/events:=strict/events',
                '-r',
                'shake/count:=strict/count',
                '-r',
                'shake/motion:=strict/motion',
                '-p',
                'threshold:=8.0',
                '-p',
                'release:=2.0',
            ]
        self.start(name, ['ros2', 'run', 'axiom_shake_detector', 'shake_detector', *args])

    def face(self):
        self.start(
            'face',
            [
                'ros2',
                'run',
                'axiom_shake_detector',
                'robot_face',
                '--ros-args',
                '-r',
                '__ns:=/axiom',
            ],
        )

    def bag_info(self, path):
        metadata = yaml.safe_load((path / 'metadata.yaml').read_text())[
            'rosbag2_bagfile_information'
        ]
        count = sum(
            t['message_count']
            for t in metadata['topics_with_message_count']
            if t['topic_metadata']['name'] == self.topic
        )
        return {
            'name': path.name,
            'samples': count,
            'duration': metadata['duration']['nanoseconds'] / 1e9,
            'started': metadata['starting_time']['nanoseconds_since_epoch'] / 1e9,
            'synthetic': path.name.startswith('synthetic-'),
        }

    def recordings(self):
        result = []
        for path in sorted(self.root.glob('*/metadata.yaml'), reverse=True):
            try:
                info = self.bag_info(path.parent)
                if info['samples']:
                    result.append(info)
            except (OSError, KeyError, TypeError, ValueError, yaml.YAMLError):
                continue
        return result

    def select_bag(self, name):
        if (
            not isinstance(name, str)
            or not name
            or any(
                c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-'
                for c in name
            )
        ):
            raise ValueError('Select a recording from the list')
        path = (self.root / name).resolve()
        if path.parent != self.root or not (path / 'metadata.yaml').is_file():
            raise ValueError('Recording not found')
        if self.bag_info(path)['samples'] == 0:
            raise ValueError('This recording contains no IMU messages')
        return path

    def finish_recording(self):
        name = self.recording
        self.stop('recorder')
        self.recording = self.record_until = None
        info = self.bag_info(self.root / name)
        if not info['samples']:
            raise ValueError('No IMU messages were recorded. Check the input and try again.')
        self.latest_recording = name
        self.record_result = info
        self.notice = (
            f'Saved {info["samples"]:,} IMU messages. You can now unplug Axiom and replay.'
        )

    def record(self, seconds):
        if self.recording:
            raise ValueError('A recording is already running')
        if self.source != 'live' or self.last_imu is None or time.monotonic() - self.last_imu > 2:
            raise ValueError('Connect live Axiom data before recording')
        if type(seconds) is not int or not 5 <= seconds <= 120:
            raise ValueError('Choose a recording duration between 5 and 120 seconds')
        name = 'movement-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f')
        qos = {
            'history': 'keep_last',
            'depth': 256,
            'reliability': 'best_effort',
            'durability': 'volatile',
        }
        override = self.root / '.teaching-qos.json'
        override.write_text(json.dumps({self.topic: qos, '/axiom/shake/motion': qos}))
        self.start(
            'recorder',
            [
                'ros2',
                'bag',
                'record',
                '--storage',
                'mcap',
                '--output',
                str(self.root / name),
                '--qos-profile-overrides-path',
                str(override),
                '--topics',
                self.topic,
                '/axiom/shake/events',
                '/axiom/shake/count',
                '/axiom/shake/motion',
            ],
        )
        self.recording, self.record_until = name, time.monotonic() + seconds
        self.record_result = None
        self.notice = 'Recording ROS messages. Shake, rest, then shake again.'

    def change_source(self, source, path=None, rate=1):
        if self.recording:
            raise ValueError('Finish the recording before changing the input')
        face_on, strict_on = self.running('face'), self.running('strict')
        for name in ('player', 'driver', 'face', 'strict', 'detector'):
            self.stop(name)
        self.source, self.bag = source, path.name if path else None
        self.reset_view()
        self.last_imu = None
        self.start_detector()
        if face_on:
            self.face()
        if strict_on:
            self.start_detector(strict=True)
        if source == 'live':
            self.start(
                'driver', ['ros2', 'run', 'axiom_driver', 'axiom_bridge_node', *self.driver_args]
            )
            self.notice = 'Live source selected. Waiting for your Axiom.'
        else:
            self.start(
                'player',
                [
                    'ros2',
                    'bag',
                    'play',
                    str(path),
                    '--topics',
                    self.topic,
                    '--rate',
                    str(rate),
                    '--delay',
                    '2',
                ],
            )
            self.notice = 'Only recorded IMU input is replayed; all reactions are computed again.'

    def submit(self, action, values):
        if self.closed.is_set() or not self.lock.acquire(blocking=False):
            raise ValueError('Another change is in progress; please wait')
        self.busy = True

        def work():
            try:
                self.error = ''
                if action == 'face_on':
                    self.face()
                    self.notice = (
                        'Robot face added: a new subscriber, with no changes to the detector.'
                    )
                elif action == 'face_off':
                    self.stop('face')
                    self.notice = (
                        'Face stopped. The driver, detector and graphs continue independently.'
                    )
                elif action == 'strict_on':
                    self.start_detector(strict=True)
                elif action == 'strict_off':
                    self.stop('strict')
                elif action == 'record':
                    self.record(values.get('seconds', 15))
                elif action == 'stop_recording':
                    if not self.recording:
                        raise ValueError('No recording is running')
                    self.finish_recording()
                elif action == 'live':
                    self.change_source('live')
                elif action in ('replay', 'sample'):
                    rate = values.get('rate', 1)
                    if type(rate) not in (int, float) or rate not in (0.5, 1, 2):
                        raise ValueError('Playback speed must be 0.5, 1 or 2')
                    if action == 'sample':
                        from .sample_bag import make_sample

                        path = self.root / (
                            'synthetic-lesson-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f')
                        )
                        make_sample(path, self.topic)
                    else:
                        path = self.select_bag(values.get('name'))
                    source = 'synthetic' if path.name.startswith('synthetic-') else 'recorded'
                    self.change_source(source, path, rate)
                else:
                    raise ValueError('Unknown teaching control')
            except Exception as exc:
                self.error = str(exc)
            finally:
                self.busy = False
                self.lock.release()

        threading.Thread(target=work, daemon=True).start()

    def watch(self):
        while not self.closed.wait(0.25):
            if self.recording and (
                time.monotonic() >= self.record_until or not self.running('recorder')
            ):
                try:
                    self.submit('stop_recording', {})
                except ValueError:
                    pass

    def snapshot(self):
        return {
            'source': self.source,
            'bag': self.bag,
            'busy': self.busy,
            'notice': self.notice,
            'error': self.error,
            'processes': {
                name: process.poll() is None for name, process in list(self.processes.items())
            },
            'recording': self.recording,
            'latest_recording': self.latest_recording,
            'record_result': self.record_result,
            'record_seconds_left': max(0, self.record_until - time.monotonic())
            if self.record_until
            else 0,
            'recordings': self.recordings(),
        }

    def close(self):
        self.closed.set()
        self.monitor.join(timeout=2)
        with self.lock:
            if self.recording:
                try:
                    self.finish_recording()
                except Exception:
                    self.stop('recorder')
            for name in list(self.processes):
                self.stop(name)
