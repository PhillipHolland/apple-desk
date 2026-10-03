#!/bin/bash
# Link Apple Desk CLIs into ~/bin and ~/.local/bin when those links are missing,
# then build local indexes with grok-desk. Contacts stay off unless you pass
# --index-contacts (forwarded to grok-desk onboard).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
mkdir -p "$HOME/bin" "$HOME/.local/bin"
link_if_needed() {
  local src="$1" dest="$2"
  if [[ -L "$dest" || -e "$dest" ]]; then
    if [[ -x "$dest" ]]; then
      echo "keep $(basename "$dest")"
      return
    fi
    rm -f "$dest"
  fi
  ln -sfn "$src" "$dest"
  echo "linked $(basename "$dest") -> $src"
}
for name in grok-reminders grok-notes grok-contacts grok-messages grok-calendar grok-shortcuts grok-mail grok-icloud grok-spotlight grok-focus grok-safari grok-desk; do
  src="$ROOT/cli/$name/bin/$name"
  if [[ -x "$src" ]]; then
    link_if_needed "$src" "$HOME/bin/$name"
    link_if_needed "$src" "$HOME/.local/bin/$name"
  else
    echo "skip $name (not in tree yet)"
  fi
done
echo "Indexes stay on this Mac under ~/.cache/grok-*. They are not uploaded."
if [[ -x "$HOME/bin/grok-desk" ]]; then
  echo "Running grok-desk onboard. Calendar, Reminders, and Mail are version checks only."
  "$HOME/bin/grok-desk" onboard "$@"
else
  echo "grok-desk is not linked yet. Install cli/grok-desk, then re-run."
fi
echo "For one-gate Mac permissions (bots): grok-desk onboard --guided"
echo "Do not commit caches or chat.db."
