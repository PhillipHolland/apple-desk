#!/bin/bash
# One-line install for Apple Desk. No sudo.
# curl -fsSL https://raw.githubusercontent.com/PhillipHolland/apple-desk/main/scripts/install.sh | bash
set -euo pipefail

REPO_URL="${APPLE_DESK_REPO:-https://github.com/PhillipHolland/apple-desk.git}"
DEST="${APPLE_DESK_HOME:-$HOME/Developer/apple-desk}"
PATH_COMMENT="# apple-desk PATH"
PATH_EXPORT='export PATH="$HOME/bin:$HOME/.local/bin:$PATH"'

if ! command -v git >/dev/null 2>&1; then
  echo "git is required. Install Xcode Command Line Tools, then re-run." >&2
  exit 1
fi

mkdir -p "$(dirname "$DEST")"
if [ -d "$DEST/.git" ]; then
  echo "Updating existing clone at $DEST"
  git -C "$DEST" pull --ff-only
elif [ -e "$DEST" ]; then
  echo "Refusing to install: $DEST exists and is not a git clone." >&2
  exit 1
else
  echo "Cloning Apple Desk into $DEST"
  git clone "$REPO_URL" "$DEST"
fi

if [ ! -x "$DEST/scripts/onboard.sh" ]; then
  echo "onboard.sh is missing from $DEST. Clone failed?" >&2
  exit 1
fi
"$DEST/scripts/onboard.sh"

# Add ~/bin and ~/.local/bin to PATH in one shell rc, once.
pick_rc() {
  case "${SHELL:-}" in
    */zsh) printf '%s\n' "$HOME/.zshrc" ;;
    */bash)
      if [ -f "$HOME/.bashrc" ] || [ ! -f "$HOME/.bash_profile" ]; then
        printf '%s\n' "$HOME/.bashrc"
      else
        printf '%s\n' "$HOME/.bash_profile"
      fi
      ;;
    *) printf '%s\n' "$HOME/.profile" ;;
  esac
}

RC="$(pick_rc)"
if [ -f "$RC" ] && grep -Fqs "$PATH_COMMENT" "$RC"; then
  echo "PATH already configured in $RC"
elif [ -f "$RC" ] && grep -Eqs '(^|[[:space:]])\$HOME/bin(:|")' "$RC" && grep -Eqs '\$HOME/\.local/bin' "$RC"; then
  echo "PATH already includes ~/bin and ~/.local/bin in $RC"
else
  touch "$RC"
  printf '\n%s\n%s\n' "$PATH_COMMENT" "$PATH_EXPORT" >> "$RC"
  echo "Added ~/bin and ~/.local/bin to PATH in $RC"
fi

echo
echo "Install finished. Open a new terminal, or run:"
echo "  export PATH=\"\$HOME/bin:\$HOME/.local/bin:\$PATH\""
echo "First win:"
echo "  grok-desk onboard --guided --quick"
echo "  grok-messages unread"
echo "Success is unread counts (no message text). Opt out of the anonymous onboard ping with GROK_DESK_NO_TELEMETRY=1."
