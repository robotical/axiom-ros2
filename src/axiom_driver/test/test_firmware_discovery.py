"""Recognise Axiom firmware without depending on optional identity metadata."""

from unittest.mock import create_autospec, Mock

from axiom_driver.core import discovery
from axiom_driver.core.discovery import is_axiom_firmware, probe_axiom_firmware
from axiom_driver.core.rpc import SessionError
import pytest


@pytest.mark.parametrize('result', ['ok', 'success'])
@pytest.mark.parametrize('name', ['Axiom009', 'Axiom018', 'AxiomNext'])
def test_successful_axiom_family_responses_are_recognised(result, name):
    assert is_axiom_firmware({'rslt': result, 'SystemName': name}) is True


def test_version_response_with_empty_optional_fields_is_recognised():
    response = {
        'req': 'v',
        'rslt': 'ok',
        'SystemName': 'Axiom018',
        'SystemVersion': '0.1.19-devlib-host',
        'MAC': '001122334455',
        'Friendly': '',
        'SerialNo': '',
        'SysTypeVers': '',
        'HwRev': '',
    }

    assert is_axiom_firmware(response) is True


def test_optional_version_and_mac_do_not_gate_recognition():
    assert is_axiom_firmware({
        'rslt': 'ok',
        'SystemName': 'Axiom018',
        'SystemVersion': None,
        'MAC': 'not-a-mac',
    }) is True


@pytest.mark.parametrize('response', [
    None,
    [],
    'Axiom018',
    18,
    True,
    {},
    {'SystemName': 'Axiom018'},
    {'rslt': 'fail', 'SystemName': 'Axiom018'},
    {'rslt': None, 'SystemName': 'Axiom018'},
    {'rslt': [], 'SystemName': 'Axiom018'},
    {'rslt': 'ok'},
    {'rslt': 'ok', 'SystemName': None},
    {'rslt': 'ok', 'SystemName': 18},
    {'rslt': 'ok', 'SystemName': []},
    {'rslt': 'ok', 'SystemName': {}},
    {'rslt': 'ok', 'SystemName': ''},
    {'rslt': 'ok', 'SystemName': 'OtherEsp32'},
    {'rslt': 'ok', 'SystemName': 'NotAxiom'},
    {'rslt': 'ok', 'SystemName': 'axiom018'},
])
def test_invalid_or_other_device_responses_are_rejected(response):
    assert is_axiom_firmware(response) is False


@pytest.fixture
def probe_session(monkeypatch):
    session = create_autospec(discovery.Session, instance=True, spec_set=True)
    monkeypatch.setattr(discovery, 'Session', Mock(return_value=session))
    yield session
    # The handshake already requests v; the probe must not issue extra commands
    # or enable a sensor subscription.
    session.request.assert_not_called()
    session.subscribe.assert_not_called()


@pytest.mark.parametrize('options, expected_timeout', [
    ({}, 2.0),
    ({'timeout': 0.25}, 0.25),
])
def test_probe_returns_full_reply_after_closing_session(probe_session, options, expected_timeout):
    response = {'rslt': 'ok', 'SystemName': 'Axiom018', 'MAC': '001122334455'}
    probe_session.connect.return_value = response

    result = probe_axiom_firmware('/virtual/axiom', **options)

    assert result is response
    probe_session.connect.assert_called_once_with(
        '/virtual/axiom', transport='serial', timeout=expected_timeout, claim_board=False,
    )
    probe_session.close.assert_called_once_with()


def test_probe_rejects_other_firmware_and_closes_session(probe_session):
    probe_session.connect.return_value = {'rslt': 'ok', 'SystemName': 'OtherEsp32'}

    assert probe_axiom_firmware('/virtual/other') is None

    probe_session.close.assert_called_once_with()


@pytest.mark.parametrize('error', [SessionError('Port busy'), KeyboardInterrupt()])
def test_probe_propagates_connection_failure_or_interrupt_and_closes_session(probe_session, error):
    probe_session.connect.side_effect = error

    with pytest.raises(type(error)) as raised:
        probe_axiom_firmware('/virtual/axiom')

    assert raised.value is error
    probe_session.close.assert_called_once_with()


def test_probe_closes_session_when_recognition_raises(probe_session, monkeypatch):
    error = RuntimeError('Unexpected recognition error')
    monkeypatch.setattr(discovery, 'is_axiom_firmware', Mock(side_effect=error))

    with pytest.raises(RuntimeError) as raised:
        probe_axiom_firmware('/virtual/axiom')

    assert raised.value is error
    probe_session.close.assert_called_once_with()
