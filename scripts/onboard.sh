#!/bin/bash
# Build/link commands, then show passive setup guidance. No automatic data indexes.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
"$ROOT/scripts/install.sh"
exec "$ROOT/cli/grok-desk/bin/grok-desk" onboard "$@"
