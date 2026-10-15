# Install Apple Desk

Clone or pull this repo, link the CLIs onto your PATH, then run a first doctor pass. No sudo.

Repo URL:

```text
https://github.com/PhillipHolland/apple-desk
```

## One-line install

```bash
curl -fsSL https://raw.githubusercontent.com/PhillipHolland/apple-desk/main/scripts/install.sh | bash
```

That script clones or `git pull --ff-only` into `~/Developer/apple-desk`, links every `grok-*` CLI, adds `~/bin` and `~/.local/bin` to PATH in one shell rc (idempotent; no sudo), then runs `grok-desk onboard --guided --quick`. Linking and PATH always finish. A failed doctor gate does not abort the install; the script prints `Installed, but onboarding needs these fixes; re-run grok-desk onboard --guided` and exits with that onboard code. A stale `~/bin/grok-desk` symlink is replaced with this checkout's binary.

Then open a new terminal (or `export PATH="$HOME/bin:$HOME/.local/bin:$PATH"`) and:

```bash
grok-messages unread
# if install stopped at a permission gate:
grok-desk onboard --guided
```

Override the clone location with `APPLE_DESK_HOME`. Opt out of the anonymous onboard ping with `GROK_DESK_NO_TELEMETRY=1` (also printed by `install.sh`).

## Clone or pull (manual)

```bash
mkdir -p ~/Developer
cd ~/Developer
if [ -d apple-desk/.git ]; then
  git -C apple-desk pull --ff-only
else
  git clone https://github.com/PhillipHolland/apple-desk.git apple-desk
fi
cd ~/Developer/apple-desk
```

Do not invent a different clone URL. Do not copy RemCTL, NotesCTL, or other third-party trees into this repo.

## Symlink CLIs (no sudo)

```bash
./scripts/onboard.sh
# optional contacts phone/email cache:
# ./scripts/onboard.sh --index-contacts
```

That script links each `cli/*/bin/grok-*` into `~/bin` and `~/.local/bin` when the link is missing, broken, or (for `grok-desk`) stale, then runs `grok-desk onboard`.

Manual equivalent:

```bash
mkdir -p ~/bin ~/.local/bin
ROOT="$HOME/Developer/apple-desk"
for name in grok-reminders grok-notes grok-contacts grok-messages grok-calendar \
            grok-shortcuts grok-mail grok-icloud grok-spotlight grok-focus \
            grok-safari grok-desk; do
  src="$ROOT/cli/$name/bin/$name"
  [ -x "$src" ] || continue
  ln -sfn "$src" "$HOME/bin/$name"
  ln -sfn "$src" "$HOME/.local/bin/$name"
done
```

All twelve CLIs in `cli/` are: `grok-desk`, `grok-messages`, `grok-notes`, `grok-reminders`, `grok-calendar`, `grok-contacts`, `grok-shortcuts`, `grok-mail`, `grok-icloud`, `grok-spotlight`, `grok-focus`, `grok-safari`.

## PATH

Ensure one of these is on your shell PATH (zsh example):

```bash
export PATH="$HOME/bin:$HOME/.local/bin:$PATH"
```

Then:

```bash
hash -r
which grok-desk grok-messages grok-notes
grok-desk --version
```

## First doctor matrix

Run each once. Do not loop on exit 3, 4, or 5 while AFK.

| CLI | Command | Expect |
| --- | --- | --- |
| desk | `grok-desk doctor --json` | tools present; signature set/unset |
| notes | `grok-notes doctor --json` | exit 0 when Automation allowed |
| contacts | `grok-contacts doctor --json` | cache or live ok |
| messages | `grok-messages doctor --json` | Automation + history (FDA) when granted |
| reminders | `grok-reminders doctor --json` | names-only lean doctor |
| calendar | `grok-calendar doctor --json` | count-only lean doctor |
| shortcuts | `grok-shortcuts doctor --json` | list ok |
| icloud | `grok-icloud doctor --json` | CloudDocs readable |
| focus | `grok-focus doctor --json` | best-effort Focus DB |
| safari | `grok-safari doctor --json` | Bookmarks.plist readable |
| spotlight | `grok-spotlight doctor --json` | `mdfind` present |
| mail | `grok-mail --version` | version only; Mail doctor can hang |

Guided Mac permissions (one gate at a time):

```bash
grok-desk onboard --guided
# same gates, skip the long Calendar/Notes/Reminders index:
grok-desk onboard --guided --quick
```

See [ONBOARD.md](./ONBOARD.md).

There is no MCP server in this repo. That is roadmap, not built.

## What stays private (never commit, never upload)

| Path | Why |
| --- | --- |
| `~/.cache/grok-*` | Local search indexes (dirs `0700`, DBs `0600`) |
| `~/.config/grok-desk/signature` | Optional one-line send footer this user chose |
| `~/.config/grok-messages/allowlist` | Optional send allowlist |
| `~/Library/Messages/chat.db` | Messages history; read-only via CLI; never copy |

Keep machine names, personal accounts, phone numbers, and baked signatures out of docs and the shareable skill. Ask for a signature; do not invent one.
