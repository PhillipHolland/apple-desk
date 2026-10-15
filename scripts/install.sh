#!/bin/bash
# One-line install for Apple Desk. No sudo.
# curl -fsSL https://raw.githubusercontent.com/PhillipHolland/apple-desk/main/scripts/install.sh | bash
#
# Linking and PATH always finish. Guided onboard runs last and does not
# abort those steps. Opt out of the anonymous onboard ping:
#   GROK_DESK_NO_TELEMETRY=1
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
  if [ "${APPLE_DESK_SKIP_FETCH:-}" = "1" ]; then
    echo "Using existing clone at $DEST"
  else
    echo "Updating existing clone at $DEST"
    git -C "$DEST" pull --ff-only
  fi
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

# Linking first. A later doctor failure must not skip this.
link_code=0
set +e
GROK_DESK_LINKS_ONLY=1 "$DEST/scripts/onboard.sh"
link_code=$?
set -e

# PATH always, even when linking or onboard later fails.
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
echo "Open a new terminal, or run:"
echo "  export PATH=\"\$HOME/bin:\$HOME/.local/bin:\$PATH\""
echo "The one anonymous onboard ping can be skipped with GROK_DESK_NO_TELEMETRY=1"

onboard_code=0
if [ -x "$HOME/bin/grok-desk" ]; then
  echo
  echo "Running grok-desk onboard --guided --quick"
  set +e
  "$HOME/bin/grok-desk" onboard --guided --quick
  onboard_code=$?
  set -e
else
  echo "grok-desk is not linked yet."
  if [ "$link_code" -ne 0 ]; then
    onboard_code="$link_code"
  else
    onboard_code=1
  fi
fi

echo
if [ "$onboard_code" -eq 0 ]; then
  echo "Install finished."
  echo "First win: grok-messages unread"
  echo "Success is unread counts (no message text)."
  echo "Opt out of the anonymous onboard ping with GROK_DESK_NO_TELEMETRY=1."
  exit 0
fi

echo "Installed, but onboarding needs these fixes; re-run grok-desk onboard --guided"
echo "CLIs are linked. PATH is in $RC. Fix the printed Settings path, then re-run."
echo "Opt out of the anonymous onboard ping with GROK_DESK_NO_TELEMETRY=1."
exit "$onboard_code"
