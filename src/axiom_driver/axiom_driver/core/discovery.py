"""Identify Axiom boards without starting sensor acquisition."""

import json
from urllib.parse import urlsplit, urlunsplit
from urllib.request import build_opener, ProxyHandler

from .session import Session


def is_axiom_firmware(firmware_response):
    """Return True if the firmware response is from an Axiom board, False otherwise."""
    if not isinstance(firmware_response, dict):
        return False

    if firmware_response.get('rslt') not in ('ok', 'success'):
        return False

    name = firmware_response.get('SystemName')
    if not isinstance(name, str):
        return False
    if not name.startswith('Axiom'):
        return False

    return True


def probe_axiom_firmware(port, timeout=2.0):
    """Read and validate a candidate's firmware response, then close its session."""
    session = Session()

    try:
        firmware_response = session.connect(
            port,
            transport='serial',
            timeout=timeout,
            claim_board=False,
        )

        if is_axiom_firmware(firmware_response):
            return firmware_response

        return None
    finally:
        session.close()


def probe_network_firmware(uri, timeout=2.0):
    """Verify an advertised HTTP endpoint without opening an acquisition socket."""
    parts = urlsplit(uri)
    if parts.scheme not in ('ws', 'wss') or not parts.hostname or parts.username:
        raise ValueError('Expected a ws:// or wss:// device URI without credentials')
    address = urlunsplit((
        'https' if parts.scheme == 'wss' else 'http', parts.netloc, '/api/v', '', '',
    ))
    # Local robot traffic must not be redirected through a host's HTTP proxy.
    with build_opener(ProxyHandler({})).open(address, timeout=timeout) as response:
        payload = response.read(65537)
    if len(payload) > 65536:
        raise ValueError('Firmware version response is too large')
    firmware = json.loads(payload)
    return firmware if is_axiom_firmware(firmware) else None
