"""Board YAML is shared by the launches and guide, including typed mappings."""

import json

from axiom_driver.config import load_boards
import pytest


def test_board_file_normalizes_names_frames_and_mapping_parameters(tmp_path):
    path = tmp_path / 'boards.yaml'
    path.write_text(json.dumps({'axioms': {
        'axiom/usb': {'transport': 'serial', 'serial.port': '/dev/serial/by-id/axiom',
                      'topic_aliases': {
                          'imu/data_raw': {'type': 'LSM6DS', 'source': 'imu/data_raw'}}},
        '/axiom/wifi': {'transport': 'ws', 'device_uri': 'ws://192.168.1.3/ws',
                        'publish_rate_hz': 20},
    }}))
    boards = load_boards(path)
    assert boards['/axiom/usb']['frame_id'] == 'axiom_usb'
    assert json.loads(boards['/axiom/usb']['topic_aliases'])['imu/data_raw']['type'] == 'LSM6DS'
    assert boards['/axiom/wifi']['publish_rate_hz'] == 20.0
    assert all(not b['auto_connect'] and not b['autosub'] for b in boards.values())


@pytest.mark.parametrize('rows, message', [
    ({'axiom': {'auto_connect': 'false'}}, 'auto_connect must be bool'),
    ({'axiom': {'unknown': 1}}, 'Invalid driver parameters'),
    ({'axiom': {}, '/axiom': {}}, 'unique namespace'),
    ({'a': {}, 'b': {}}, 'unique namespace'),
])
def test_invalid_board_configuration_fails_before_starting_nodes(tmp_path, rows, message):
    path = tmp_path / 'boards.yaml'
    path.write_text(json.dumps({'axioms': rows}))
    with pytest.raises(ValueError, match=message):
        load_boards(path)
