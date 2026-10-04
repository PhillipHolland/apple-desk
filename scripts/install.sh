#!/bin/bash
# Build the local helper and link the combined CLI. Never request permissions here.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
if [[ "${1:-}" == "--skip-build" ]]; then
  shift
else
  "$ROOT/native/build.sh"
fi
exec python3 "$ROOT/scripts/install.py" "$@"
