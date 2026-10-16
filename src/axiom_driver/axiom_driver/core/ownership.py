"""Nonblocking, per-user ownership of host-driver endpoints and physical boards."""

import fcntl
import hashlib
import os
from pathlib import Path
import re
import tempfile
from urllib.parse import urlsplit, urlunsplit


def normalise_board_id(value):
    """Return the firmware's canonical MAC identity, or None if unavailable."""
    if not isinstance(value, str):
        return None
    value = value.replace(':', '').replace('-', '').lower()
    if re.fullmatch('[0-9a-f]{12}', value) and value != '000000000000':
        return value
    return None


def endpoint_key(transport, address):
    """Treat a serial symlink and its tty as the same connection."""
    if transport == 'serial':
        return 'serial:' + os.path.realpath(address)
    parts = urlsplit(address)
    port = parts.port or (443 if parts.scheme == 'wss' else 80)
    host = (parts.hostname or '').lower()
    # A board has one acquisition owner even when callers choose different WS paths.
    return urlunsplit((parts.scheme, f'{host}:{port}', '', '', ''))


def claim(key):
    """Hold an advisory lock until the returned file is closed; never wait."""
    directory = Path(tempfile.gettempdir()) / f'axiom-ros2-{os.getuid()}'
    directory.mkdir(mode=0o700, exist_ok=True)
    path = directory / (hashlib.sha256(key.encode()).hexdigest() + '.lock')
    handle = path.open('a')
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        handle.close()
        raise OSError('Axiom is already owned by another host-driver session') from exc
    return handle
