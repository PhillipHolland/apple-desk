#!/bin/bash
# Run every offline test_*.py under cli/. No sudo. No network required.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export GROK_DESK_NO_TELEMETRY="${GROK_DESK_NO_TELEMETRY:-1}"
fail=0
count=0
while IFS= read -r -d '' f; do
  count=$((count + 1))
  echo "== ${f#"$ROOT/"}"
  if ! python3 "$f"; then
    fail=1
  fi
done < <(find "$ROOT/cli" -name 'test_*.py' -print0 | sort -z)
if [ "$count" -eq 0 ]; then
  echo "no tests found" >&2
  exit 1
fi
if [ "$fail" -ne 0 ]; then
  echo "offline tests failed" >&2
  exit 1
fi
echo "ok $count test files"
