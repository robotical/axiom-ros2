"""Check package style with the same ROS tools as the other demo packages."""

import pytest

pytest.importorskip('ament_flake8')
from ament_flake8.main import main_with_errors  # noqa: E402,I100
from ament_pep257.main import main  # noqa: E402


def test_flake8():
    """Check Python formatting and imports."""
    rc, errors = main_with_errors(argv=[])
    assert rc == 0, '\n'.join(errors)


def test_pep257():
    """Check public documentation strings."""
    assert main(argv=['.', 'test']) == 0
