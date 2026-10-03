# Install Apple Desk

Clone or pull this repo, link the CLIs onto your PATH, then run a first doctor pass. No sudo.

Repo URL (public-shaped; may still be private until release):

```text
https://github.com/PhillipHolland/apple-desk
```

## Clone or pull

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

That script links each `cli/*/bin/grok-*` into `~/bin` and `~/.local/bin` when the link is missing or broken, then runs `grok-desk onboard`.

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

Guided Mac permissions (one gate at a time):

```bash
grok-desk onboard --guided
```

See [ONBOARD.md](./ONBOARD.md).

## What stays private (never commit, never upload)

| Path | Why |
| --- | --- |
| `~/.cache/grok-*` | Local search indexes (dirs `0700`, DBs `0600`) |
| `~/.config/grok-desk/signature` | Optional one-line send footer this user chose |
| `~/.config/grok-messages/allowlist` | Optional send allowlist |
| `~/Library/Messages/chat.db` | Messages history; read-only via CLI; never copy |

Keep machine names, personal accounts, phone numbers, and baked signatures out of docs and the shareable skill. Ask for a signature; do not invent one.
