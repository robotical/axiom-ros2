"""Selection, angle encoding and latest-target handling without ROS dependencies."""

from dataclasses import dataclass
import math
import re

from axiom_driver.core.commands import encode_command


@dataclass(frozen=True)
class ServoBinding:
    """One live device revision and its advertised command services."""

    topic: str
    revision: int
    angle_service: str
    enable_service: str
    angle: dict


def select_servo(rows, selector='', angle_command='angle', enable_command='enable'):
    """Select exactly one online device with compatible angle and enable commands."""
    candidates = []
    for row in rows:
        if (not row.get('online') or row.get('stale') or not row.get('metadata_ready')
                or not row.get('topic') or (selector and row['topic'] != selector)):
            continue
        commands = {item['name']: item for item in row.get('commands', [])}
        if angle_command not in commands or enable_command not in commands:
            continue
        angle, enable = commands[angle_command], commands[enable_command]
        action = angle['descriptor']
        # A slider controls one scalar. Do not infer how to populate multi-field commands.
        if action.get('vt') or not re.fullmatch(r'[<>!]?[bBhHiIlLqQfd]', action.get('t', '')):
            continue
        try:
            encode_command(enable['descriptor'], [0.0])
            encode_command(enable['descriptor'], [1.0])
            scale = float(action.get('mul', 1))
            offset = float(action.get('sub', 0))
            if not math.isfinite(scale) or scale == 0 or not math.isfinite(offset):
                continue
        except (ValueError, TypeError, OverflowError):
            continue
        paths = (angle['service'], enable['service'])
        if not all(path.startswith(row['topic'] + '/commands/') for path in paths):
            continue
        candidates.append(ServoBinding(
            row['topic'], row['revision'], *paths, dict(action)))
    if not candidates:
        raise ValueError('Waiting for an online device with angle and enable commands')
    if len(candidates) != 1:
        raise ValueError('Multiple servos found; set servo:= to one inventory topic root')
    return candidates[0]


def command_value(action, position, unit, lower, upper):
    """Convert radians to descriptor units and round to its integer wire resolution."""
    if not math.isfinite(position) or not lower <= position <= upper:
        raise ValueError('Slider angle is nonfinite or outside the configured demo limits')
    if unit not in ('degrees', 'radians'):
        raise ValueError('command_unit must be degrees or radians')
    value = math.degrees(position) if unit == 'degrees' else position
    limits = action.get('r')
    if limits and not float(limits[0]) <= value <= float(limits[1]):
        raise ValueError('Slider angle is outside the live descriptor limits')
    if action['t'][-1] not in 'fd':
        scale, offset = float(action.get('mul', 1)), float(action.get('sub', 0))
        value = round((value - offset) * scale) / scale + offset
    rounded_position = math.radians(value) if unit == 'degrees' else value
    if not lower - 1e-12 <= rounded_position <= upper + 1e-12:
        raise ValueError('Rounded angle is outside the configured demo limits')
    # Apply the driver's own validation too, including range and wire-size checks.
    encode_command(action, [value])
    return value


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
