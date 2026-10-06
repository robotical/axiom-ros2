"""Check the new package with the repository's ROS style tools."""

from ament_flake8.main import main_with_errors
from ament_pep257.main import main


def test_flake8():
    rc, errors = main_with_errors(argv=[])
    assert rc == 0, '\n'.join(errors)


def test_pep257():
    assert main(argv=['.', 'test']) == 0
