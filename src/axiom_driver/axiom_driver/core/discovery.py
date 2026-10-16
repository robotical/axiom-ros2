"""Identify Axiom boards from their firmware version responses."""

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
            timeout=timeout
        )

        if is_axiom_firmware(firmware_response):
            return firmware_response

        return None
    finally:
        session.close()
