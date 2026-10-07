"""Portable console setup must work outside the checkout and with paths containing spaces."""

import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]


def run_setup(tmp_path, config, **overrides):
    env = {k: v for k, v in os.environ.items()
           if not k.startswith(('ROS_', 'AXIOM_')) and k != 'AMENT_PREFIX_PATH'}
    env.update(AXIOM_MACHINE_CONFIG=str(config), **overrides)
    return subprocess.run(
        ['bash', '-uc', 'source "$1" || exit; '
         'printf "%s\\n" "$ROS_WORKSPACE" "$ROS_DOMAIN_ID" "$AXIOM_DASHBOARD_PORT" '
         '"${AXIOM_ROS_BOARDS_FILE:-}" "${UNDERLAY_READY:-}" "${OVERLAY_READY:-}"',
         'setup-test', str(ROOT / 'scripts/setup_env.sh')],
        cwd=tmp_path, env=env, text=True, capture_output=True,
    )


def test_configured_workspace_underlay_and_board_paths(tmp_path):
    workspace = tmp_path / 'workspace with spaces'
    (workspace / 'install').mkdir(parents=True)
    (workspace / 'install/setup.bash').write_text('export OVERLAY_READY=yes\n')
    underlay = tmp_path / 'ROS setup.bash'
    underlay.write_text('export UNDERLAY_READY=yes\n: "${UNSET_ROS_VARIABLE}"\n')
    boards = tmp_path / 'my boards.yaml'
    boards.write_text('axioms: {}\n')
    config = tmp_path / 'machine.env'
    config.write_text(
        f'ROS_WORKSPACE="{workspace}"\nROS_SETUP_FILE="{underlay}"\n'
        f'AXIOM_ROS_BOARDS_FILE="{boards}"\nROS_DOMAIN_ID=57\nAXIOM_DASHBOARD_PORT=8085\n'
    )
    result = run_setup(tmp_path, config)
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [str(workspace), '57', '8085', str(boards), 'yes', 'yes']


def test_workspace_defaults_to_checkout_instead_of_current_directory(tmp_path):
    underlay = tmp_path / 'setup.bash'
    underlay.write_text('export UNDERLAY_READY=yes\n')
    config = tmp_path / 'machine.env'
    config.write_text(f'ROS_SETUP_FILE="{underlay}"\n')
    result = run_setup(tmp_path, config, ROS_DOMAIN_ID='61')
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[:3] == [str(ROOT), '61', '8083']


@pytest.mark.parametrize('setting, message', [
    ('ROS_SETUP_FILE', 'ROS setup not found'),
    ('ROS_WORKSPACE', 'ROS workspace not found'),
    ('AXIOM_ROS_BOARDS_FILE', 'Board configuration not found'),
])
def test_missing_explicit_paths_fail_with_actionable_error(tmp_path, setting, message):
    underlay = tmp_path / 'setup.bash'
    underlay.write_text(':\n')
    config = tmp_path / 'machine.env'
    config.write_text(f'ROS_SETUP_FILE="{underlay}"\n{setting}="{tmp_path}/missing"\n')
    result = run_setup(tmp_path, config)
    assert result.returncode != 0
    assert message in result.stderr
