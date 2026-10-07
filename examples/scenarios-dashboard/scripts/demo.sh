#!/usr/bin/env bash
# Compatibility entry point for the optional Mac runtime.
set -euo pipefail
demo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
exec "$demo_root/platforms/macos/demo.sh" "$@"
