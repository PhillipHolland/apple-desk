# Contributing to Apple Desk

Apple Desk is a set of Mac-local CLIs. Changes must work for any user on any Mac. See [`GENERALIZE.md`](./GENERALIZE.md).

## Setup

```bash
git clone https://github.com/PhillipHolland/apple-desk.git
cd apple-desk
# optional: ./scripts/onboard.sh   # needs a Mac
```

Requirements to edit and run offline tests: Python 3.9+ and a checkout of this repo. Live Apple-app doctors need a Mac, `osascript` / JXA, Automation, and Full Disk Access for Messages history.

There is no MCP server to run. That is roadmap, not built.

## Tests

Offline tests do not need a Mac and must not read a live `~/Library` or `~/.cache/grok-*`.

```bash
./scripts/test.sh
```

That runs every `test_*.py` under `cli/`. Add tests next to the CLI you change. Do not require pytest.

If you touch `grok-desk onboard`, cover human-mode `[n/11]` progress on stderr, `--json` stdout staying one JSON object, `--quick` skipping or narrowing indexes, and the existing gate order plus exit codes.

## Safety

Do not weaken send or consent gates.

- `grok-messages send` stays a dry-run unless `--force --confirm TOKEN` after a human yes.
- `--to` stays 1:1. Groups need `--chat-guid` after the user named that group.
- Deletes and other writes stay a dry-run unless `--force`.
- `chat.db` stays read-only.

Do not commit caches, `chat.db`, contact dumps, signatures, phone numbers, emails, or machine-specific `/Users/...` paths. Do not invent a signature line.

## Pull requests

Use the PR template. Point at `main`. Leave existing draft PRs (#2, #3) alone unless a maintainer asks.

License is MIT. By contributing you agree your changes are MIT, copyright Phillip Holland 2026 unless a maintainer says otherwise.
