#!/bin/bash
set -euo pipefail
ROOT=$(cd "$(dirname "$0")" && pwd)
export CLANG_MODULE_CACHE_PATH="$ROOT/.build/module-cache"
export SWIFTPM_MODULECACHE_OVERRIDE="$CLANG_MODULE_CACHE_PATH"
DEVELOPER=$(xcode-select -p)
FRAMEWORKS="$DEVELOPER/Library/Developer/Frameworks"
RUNTIME="$DEVELOPER/Library/Developer/usr/lib"
EXTRA=()
if [ -d "$FRAMEWORKS/Testing.framework" ]; then
  EXTRA=(-Xswiftc -F -Xswiftc "$FRAMEWORKS" -Xlinker "-F$FRAMEWORKS" -Xlinker -rpath -Xlinker "$FRAMEWORKS" -Xlinker -rpath -Xlinker "$RUNTIME")
fi
swift test --disable-sandbox --manifest-cache local --disable-xctest --enable-swift-testing --package-path "$ROOT" --scratch-path "$ROOT/.build" -Xswiftc -target -Xswiftc "$(uname -m)-apple-macosx14.0" "${EXTRA[@]}"
