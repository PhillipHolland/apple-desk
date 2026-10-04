#!/bin/bash
# Offline regression suite. Never grants permissions or touches Mail/Calendar data.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
python3 -m unittest discover -s tests -v
"$ROOT/native/test.sh"
