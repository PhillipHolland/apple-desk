#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
export CLANG_MODULE_CACHE_PATH="$ROOT/.build/module-cache"
export SWIFTPM_MODULECACHE_OVERRIDE="$CLANG_MODULE_CACHE_PATH"
mkdir -p "$CLANG_MODULE_CACHE_PATH" "$ROOT/dist"
ARCH=$(uname -m)
swift build --disable-sandbox --manifest-cache local --package-path "$ROOT" --scratch-path "$ROOT/.build" -c release -Xswiftc -target -Xswiftc "$ARCH-apple-macosx14.0"
BIN=$(swift build --disable-sandbox --manifest-cache local --package-path "$ROOT" --scratch-path "$ROOT/.build" -c release --show-bin-path)
cp "$BIN/apple-desk-calendar" "$ROOT/dist/apple-desk-calendar"
codesign --force --sign - --entitlements "$ROOT/entitlements.plist" --identifier local.apple-desk.calendar "$ROOT/dist/apple-desk-calendar"
printf '%s\n' "$ROOT/dist/apple-desk-calendar"
