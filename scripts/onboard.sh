#!/bin/bash
# Link Apple Desk CLIs into ~/bin and ~/.local/bin on this Mac.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$HOME/bin" "$HOME/.local/bin"
for name in grok-reminders grok-notes grok-contacts grok-messages grok-calendar grok-shortcuts grok-mail grok-icloud; do
  src="$ROOT/cli/$name/bin/$name"
  if [[ -x "$src" ]]; then
    ln -sfn "$src" "$HOME/bin/$name"
    ln -sfn "$src" "$HOME/.local/bin/$name"
    echo "linked $name"
  else
    echo "skip $name (not in tree yet)"
  fi
done
echo "Run each tool's doctor next. Do not commit caches or chat.db."
