"""Select a topic-controlled servo and gate joint-slider targets."""

from dataclasses import dataclass
import math

from axiom_driver.core.commands import encode_command


@dataclass(frozen=True)
class ServoBinding:
    """One live device revision, angle topic and enable service."""

    topic: str
    revision: int
    angle_topic: str
    enable_service: str


def select_servo(rows, selector='', enable_command='enable'):
    """Select one live radian-angle topic with an acknowledged enable service."""
    candidates = []
    for row in rows:
        if (not row.get('online') or row.get('stale') or not row.get('metadata_ready')
                or not row.get('topic') or (selector and row['topic'] != selector)):
            continue
        commands = {item['name']: item for item in row.get('commands', [])}
        angles = [item for item in row.get('command_topics', [])
                  if item.get('kind') == 'angle' and item.get('unit') == 'rad'
                  and item.get('message_type') == 'std_msgs/msg/Float64']
        if len(angles) != 1 or enable_command not in commands:
            continue
        angle, enable = angles[0], commands[enable_command]
        try:
            encode_command(enable['descriptor'], [0.0])
            encode_command(enable['descriptor'], [1.0])
        except (ValueError, TypeError, OverflowError):
            continue
        paths = (angle['topic'], enable['service'])
        if not all(path.startswith(row['topic'] + '/commands/') for path in paths):
            continue
        candidates.append(ServoBinding(
            row['topic'], row['revision'], *paths))
    if not candidates:
        raise ValueError('Waiting for an online device with angle and enable commands')
    if len(candidates) != 1:
        raise ValueError('Multiple servos found; set servo:= to one inventory topic root')
    return candidates[0]


def joint_position(names, positions, joint):
    """Extract one named position, rejecting malformed or ambiguous command arrays."""
    if len(names) != len(positions) or names.count(joint) > 1:
        raise ValueError('Joint command needs matching name/position arrays and unique names')
    if joint not in names:
        return None
    value = float(positions[names.index(joint)])
    if not math.isfinite(value):
        raise ValueError('Joint angle must be finite')
    return value


class TargetGate:
    """Require arming and a subsequent change; keep only the newest target."""

    def __init__(self):
        self.latest = self.baseline = self.desired = None
        self.armed = False

    def observe(self, value):
        """Remember the GUI position, including while disarmed."""
        self.latest = value
        if self.armed:
            if self.baseline is None:
                self.baseline = value
            else:
                self.desired = value

    def arm(self):
        """Use the current slider position as a baseline without commanding it."""
        self.armed = True
        self.baseline = self.latest
        self.desired = None

    def disarm(self):
        """Drop pending angles and require another acknowledged enable."""
        self.armed = False
        self.desired = None

    def next_target(self):
        """Return a changed target only when armed."""
        if self.armed and self.desired is not None and self.desired != self.baseline:
            return self.desired
        return None

    def sent(self, value):
        """Deduplicate the value dispatched to firmware while preserving newer input."""
        self.baseline = value
