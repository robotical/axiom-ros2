#!/usr/bin/env bash
# Source this file. It prepares the terminal; starting ROS nodes stays manual.
_axiom_setup_env() {
  local repo config auto_export nounset result
  repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd) || return
  export AXIOM_ROS_ROOT="$repo"
  config=${AXIOM_MACHINE_CONFIG:-$repo/config/machine.env}
  if [[ -f "$config" ]]; then
    auto_export=$-
    set -a
    source "$config"
    result=$?
    [[ $auto_export == *a* ]] || set +a
    [[ $result == 0 ]] || return "$result"
  elif [[ -n ${AXIOM_MACHINE_CONFIG:-} ]]; then
    printf 'Machine configuration not found: %s\n' "$config" >&2
    return 1
  fi
  export ROS_WORKSPACE=${ROS_WORKSPACE:-$repo}
  [[ $ROS_WORKSPACE == /* ]] || ROS_WORKSPACE="$repo/$ROS_WORKSPACE"
  if [[ ! -d "$ROS_WORKSPACE" ]]; then
    printf 'ROS workspace not found: %s\n' "$ROS_WORKSPACE" >&2
    return 1
  fi
  export ROS_SETUP_FILE=${ROS_SETUP_FILE:-/opt/ros/${ROS_DISTRO:-jazzy}/setup.bash}
  if [[ ! -r "$ROS_SETUP_FILE" ]]; then
    printf 'ROS setup not found: %s. Set ROS_SETUP_FILE in %s.\n' "$ROS_SETUP_FILE" "$config" >&2
    return 1
  fi
  export ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}
  export AXIOM_DASHBOARD_PORT=${AXIOM_DASHBOARD_PORT:-8083}
  if [[ -z ${AXIOM_ROS_BOARDS_FILE:-} && -f "$repo/config/boards.yaml" ]]; then
    export AXIOM_ROS_BOARDS_FILE="$repo/config/boards.yaml"
  fi
  if [[ -n ${AXIOM_ROS_BOARDS_FILE:-} ]]; then
    [[ $AXIOM_ROS_BOARDS_FILE == /* ]] || AXIOM_ROS_BOARDS_FILE="$repo/$AXIOM_ROS_BOARDS_FILE"
    export AXIOM_ROS_BOARDS_FILE
    if [[ ! -r "$AXIOM_ROS_BOARDS_FILE" ]]; then
      printf 'Board configuration not found: %s\n' "$AXIOM_ROS_BOARDS_FILE" >&2
      return 1
    fi
  fi
  # ROS-generated setup scripts may reference unset variables.
  nounset=$-
  set +u
  source "$ROS_SETUP_FILE"
  result=$?
  if [[ $result == 0 && -f "$ROS_WORKSPACE/install/setup.bash" ]]; then
    source "$ROS_WORKSPACE/install/setup.bash"
    result=$?
  fi
  [[ $nounset != *u* ]] || set -u
  return "$result"
}
_axiom_setup_env
