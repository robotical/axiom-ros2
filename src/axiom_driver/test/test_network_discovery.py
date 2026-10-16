"""Network verification is non-acquiring; mDNS only supplies candidate endpoints."""

from types import SimpleNamespace
from unittest.mock import Mock

from axiom_driver.core.discovery import probe_network_firmware
from axiom_driver.core.ownership import claim, endpoint_key, normalise_board_id
from axiom_driver.core.rpc import SessionError
from axiom_driver.core.session import Session
import pytest
from test_serial_integration import SerialFirmware
from test_session import FirmwareServer

zeroconf = pytest.importorskip('zeroconf')
from axiom_driver.core.network_discovery import NetworkDiscovery  # noqa: E402,I100

ID_A = '001122334455'


@pytest.mark.parametrize('value, expected', [
    ('00:11:22:33:44:55', ID_A), ('00-11-22-33-44-55', ID_A),
    ('AABBCCDDEEFF', 'aabbccddeeff'), ('000000000000', None),
    ('bad', None), ('Axiom018', None), (None, None), (123, None),
])
def test_mac_identity_normalisation(value, expected):
    assert normalise_board_id(value) == expected


def test_endpoint_aliases_share_the_same_lock_key(tmp_path):
    device = tmp_path / 'tty'
    device.touch()
    alias = tmp_path / 'by-id'
    alias.symlink_to(device)
    assert endpoint_key('serial', str(alias)) == endpoint_key('serial', str(device))
    assert endpoint_key('ws', 'ws://EXAMPLE/ws') == endpoint_key('ws', 'ws://example:80/other')


def test_ownership_is_nonblocking_and_released_when_closed():
    lease = claim('test:discovery-ownership')
    try:
        with pytest.raises(OSError, match='already owned'):
            claim('test:discovery-ownership')
    finally:
        lease.close()
    claim('test:discovery-ownership').close()


def test_active_serial_endpoint_cannot_be_probed_by_second_session():
    peer = SerialFirmware()
    first, second = Session(), Session()
    try:
        first.connect(peer.path, transport='serial', timeout=0.5)
        with pytest.raises(SessionError, match='already owned'):
            second.connect(peer.path, transport='serial', timeout=0.5)
        assert peer.commands == ['v']
        assert first.connected and first.ping(timeout=0.5) >= 0
        first.close()
        second.connect(peer.path, transport='serial', timeout=0.5)
        assert second.connected
    finally:
        first.close()
        second.close()
        peer.close()


def test_wifi_probe_does_not_acquire_or_open_a_websocket(monkeypatch):
    peer = FirmwareServer(firmware={'SystemName': 'Axiom018', 'MAC': ID_A})
    monkeypatch.setenv('http_proxy', 'http://127.0.0.1:1')
    try:
        response = probe_network_firmware(peer.uri, timeout=1)
        assert response['MAC'] == ID_A
        assert not peer.connections and not peer.paths and not peer.commands
    finally:
        peer.close()


def test_one_physical_board_cannot_have_usb_and_wifi_acquisition_owners():
    version = {'SystemName': 'Axiom018', 'MAC': ID_A}
    usb = SerialFirmware(version_response=version)
    wifi = FirmwareServer(firmware=version)
    first, second = Session(), Session()
    try:
        first.connect(usb.path, transport='serial', timeout=1)
        # HTTP discovery remains harmless while another transport owns acquisition.
        assert probe_network_firmware(wifi.uri, timeout=1)['MAC'] == ID_A
        with pytest.raises(SessionError, match='already owned'):
            second.connect(wifi.uri, timeout=1)
        assert first.connected
        assert not second.connected and not wifi.commands
        first.close()
        second.connect(wifi.uri, timeout=1)
        assert second.connected
    finally:
        first.close()
        second.close()
        usb.close()
        wifi.close()


def test_non_axiom_network_service_is_rejected():
    peer = FirmwareServer(firmware={'SystemName': 'OtherEsp32'})
    try:
        assert probe_network_firmware(peer.uri, timeout=1) is None
        assert not peer.connections
    finally:
        peer.close()


@pytest.mark.parametrize('uri', ['http://192.0.2.1', 'ws://', 'ws://user@192.0.2.1/ws'])
def test_invalid_network_endpoint_fails_without_a_request(uri):
    with pytest.raises(ValueError):
        probe_network_firmware(uri)


def test_mdns_updates_removal_filtering_and_snapshot(monkeypatch):
    module = __import__('axiom_driver.core.network_discovery', fromlist=['NetworkDiscovery'])
    service = SimpleNamespace(properties={b'board': b'esp32'}, port=80,
                              parsed_addresses=Mock(return_value=['192.0.2.10']))
    zc = Mock()
    zc.get_service_info.return_value = service
    browser = Mock()
    monkeypatch.setattr(module, 'Zeroconf', Mock(return_value=zc))
    monkeypatch.setattr(module, 'ServiceBrowser', Mock(return_value=browser))
    discovery = NetworkDiscovery()
    try:
        discovery.add_service(zc, '_http._tcp.local.', 'board._http._tcp.local.')
        assert discovery.snapshot() == ('ws://192.0.2.10:80/ws',)
        service.parsed_addresses.return_value = ['192.0.2.11']
        discovery.update_service(zc, '_http._tcp.local.', 'board._http._tcp.local.')
        assert discovery.snapshot() == ('ws://192.0.2.11:80/ws',)
        service.properties = {}
        discovery.add_service(zc, '_http._tcp.local.', 'printer._http._tcp.local.')
        assert len(discovery.snapshot()) == 1
        discovery.remove_service(zc, '_http._tcp.local.', 'board._http._tcp.local.')
        assert discovery.snapshot() == ()
    finally:
        discovery.close()
    browser.cancel.assert_called_once_with()
    zc.close.assert_called_once_with()
