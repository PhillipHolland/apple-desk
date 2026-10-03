# Apple Desk

Mac-local Apple ecosystem tools for Grok Bot / agents, plus a planned single MCP server.

**Status:** private WIP. Keep this repo private until release.

Agent skill: see [`SKILL.md`](./SKILL.md) (also installed as the Apple Desk skill in Grok Bot).

## Quick install (this Mac)

```bash
./scripts/onboard.sh
# links CLIs if missing, then: grok-desk onboard
# contacts cache stays off unless: ./scripts/onboard.sh --index-contacts
```

## CLIs (under `cli/`)

| CLI | Role |
| --- | --- |
| `grok-reminders` | Reminders 0.1.4 (in-house; dry-run add; names-only doctor) |
| `grok-notes` | Notes.app + search cache (0.2.1, `tags --folder`) |
| `grok-contacts` | Contacts.app 0.1.2 (cache-first search/show; `--live` for Contacts.app) |
| `grok-messages` | Messages 0.2.1 send (gated) + chat.db history + attachment metadata |
| `grok-calendar` | Calendar.app 0.1.5 (count-only doctor; cache-first list/search) |
| `grok-shortcuts` | Shortcuts 0.1.2 list/run/create (`run` and `create` need `--force`) |
| `grok-mail` | Mail.app 0.1.2 (blocked on Automation Allow; prefer Gmail connector) |
| `grok-icloud` | iCloud Drive 0.1.1 list/read/summary (no force-download) |
| `grok-spotlight` | Scoped `mdfind` (paths only; 0.1.0) |
| `grok-desk` | Onboarding and local indexes (0.1.4). Contacts cache off by default. Optional one-line signature |
| `grok-focus` | Focus status 0.1.1 (best-effort; set needs `--force` and a shortcut) |
| `grok-safari` | Safari bookmarks + Reading List 0.1.1 (read-only plist) |

Requires macOS Automation (and Full Disk Access for Messages history).

## Hard rules (Messages)

- Never send without user pre-approval of recipient + exact text, including the signature line when one is set.
- Never resolve a person to a group chat (`--to` is 1:1 only).
- Groups need `--chat-guid` after the user named that group.
- Signature is `grok-desk signature` (`~/.config/grok-desk/signature`). The send CLI does not append it.

## Credits

Reminders-pattern inspiration: Federico Viticci / MacStories RemCTL — not vendored here.

## Privacy

Do not commit `~/.cache/grok-*`, `chat.db`, contact dumps, or secrets. Indexes never leave the Mac.
