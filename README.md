# Apple Desk

Mac-local Apple ecosystem tools for Grok Bot / agents, plus a planned single MCP server.

**Status:** public at https://github.com/PhillipHolland/apple-desk.

Agent skill: see [`SKILL.md`](./SKILL.md) (also installed as the Apple Desk skill in Grok Bot).

## Quick install

See [`docs/INSTALL.md`](./docs/INSTALL.md) (clone URL, symlinks, PATH, doctor matrix) and [`docs/ONBOARD.md`](./docs/ONBOARD.md) (guided gates).

```bash
git clone https://github.com/PhillipHolland/apple-desk.git ~/Developer/apple-desk
cd ~/Developer/apple-desk
./scripts/onboard.sh
# guided permissions (bot-friendly; stops with System Settings path):
grok-desk onboard --guided
# contacts cache stays off unless: ./scripts/onboard.sh --index-contacts
```

## CLIs (under `cli/`)

| CLI | Role |
| --- | --- |
| `grok-reminders` | Reminders 0.1.4 (in-house; dry-run add; names-only doctor) |
| `grok-notes` | Notes.app + search cache (0.2.1, `tags --folder`) |
| `grok-contacts` | Contacts.app 0.1.2 (cache-first search/show; `--live` for Contacts.app) |
| `grok-messages` | Messages 0.2.7 (shipped mark-read, history, unread, gated send) |
| `grok-calendar` | Calendar.app 0.1.5 (count-only doctor; cache-first list/search) |
| `grok-shortcuts` | Shortcuts 0.1.2 list/run/create (`run` and `create` need `--force`) |
| `grok-mail` | Mail.app 0.1.2 (blocked on Automation Allow; prefer Gmail connector) |
| `grok-icloud` | iCloud Drive 0.1.1 list/read/summary (no force-download) |
| `grok-spotlight` | Scoped `mdfind` (paths only; 0.1.0) |
| `grok-desk` | Onboarding and local indexes (0.1.7). Contacts cache off by default. Optional one-line signature |
| `grok-focus` | Focus status 0.1.1 (best-effort; set needs `--force` and a shortcut) |
| `grok-safari` | Safari bookmarks + Reading List 0.1.1 (read-only plist) |

Requires macOS Automation (and Full Disk Access for Messages history).

## Hard rules (Messages)

- Never send without user pre-approval of recipient + exact text, including the signature line when one is set.
- Never resolve a person to a group chat (`--to` is 1:1 only).
- Groups need `--chat-guid` after the user named that group.
- Signature is `grok-desk signature` (`~/.config/grok-desk/signature`). The send CLI does not append it.

## Principles

Apple Desk runs on the user's Mac, for that user. It is not an Apple product. Nobody else endorses it.

- Local only. Indexes stay in `~/.cache/grok-*` (directories `0700`, databases `0600`). Nothing uploads `chat.db`, contacts, notes, or message text.
- Permission is honest. Full Disk Access is what lets a process read Messages history. Automation Allow is what lets a process control an app. A timeout is a hang or a dialog still on screen, not proof the user clicked Deny.
- Outbound and destructive actions wait. Draft the recipient and the exact text, then send only after an explicit yes and `grok-messages send --force`. `--to` is 1:1. A group is used only when the user named that group (`--chat-guid`). Deletes need `--force`. The signature is opt-in (`grok-desk signature`) and is not appended by the send CLI.
- The agent acts for the user. It does not message, mail, or change data on its own.


## OSS neighbors

Credit only. Nothing here is vendored, and this project does not copy their source. Apple Desk is in-house. It is not an Apple product, and none of these projects endorse it.

Patterns worth learning from them: EventKit is a better long-term path than AppleScript for Calendar and Reminders; say which TCC grant you actually need; prefer a `status` or `doctor` plus `--json`. We still talk to Calendar and Reminders through the apps today. Switching those reads to EventKit is future work, not a copy of anyone's tree.

- [openclaw/openclaw](https://github.com/openclaw/openclaw) and [openclaw/imsg](https://github.com/openclaw/imsg) — iMessage over a local JSON-RPC CLI (`brew install steipete/tap/imsg`). We read `chat.db` ourselves and send only through Messages.app after an explicit yes.
- [omarshahine/Apple-PIM-Agent-Plugin](https://github.com/omarshahine/Apple-PIM-Agent-Plugin) — EventKit Swift CLIs aimed at OpenClaw.
- [tonyhth/openclaw-apple-calendar](https://github.com/tonyhth/openclaw-apple-calendar) — calendar bridge for OpenClaw.
- [danielhopkins/apple-tools](https://github.com/danielhopkins/apple-tools) — MIT. Closest peer. See `prior-art.md` in that repo.
- [54yyyu/pyapple-mcp](https://github.com/54yyyu/pyapple-mcp), [krmj22/macos-mcp](https://github.com/krmj22/macos-mcp), [more-io/claude-apple-bridges](https://github.com/more-io/claude-apple-bridges) — other public MCP or bridge shapes. We do not import them.

Do not vendor or copy proprietary third-party source into this repo.

## Privacy

Do not commit `~/.cache/grok-*`, `chat.db`, contact dumps, or secrets. Indexes never leave the Mac.
