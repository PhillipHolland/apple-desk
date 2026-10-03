# Apple Desk

Mac-local Apple ecosystem tools for Grok Bot / agents, plus a planned single MCP server.

**Status:** private WIP. Keep this repo private until release.

Agent skill: see [`SKILL.md`](./SKILL.md) (also installed as the Apple Desk skill in Grok Bot).

## Quick install (this Mac)

```bash
./scripts/onboard.sh
```

## CLIs (under `cli/`)

| CLI | Role |
| --- | --- |
| `grok-reminders` | Reminders 0.1.1 (in-house; RemCTL not a dependency; blocked on Automation Allow) |
| `grok-notes` | Notes.app + search cache |
| `grok-contacts` | Contacts.app |
| `grok-messages` | Messages send (gated) + chat.db history |
| `grok-calendar` | Calendar.app (0.1.1; blocked on Automation Allow) |
| `grok-shortcuts` | Shortcuts list/run (`run` needs `--force`) |
| `grok-mail` | Mail.app (0.1.1; blocked on Automation Allow; prefer Gmail connector) |
| `grok-icloud` | iCloud Drive list/read (local only; no force-download) |

Requires macOS Automation (and Full Disk Access for Messages history).

## Hard rules (Messages)

- Never send without user pre-approval of recipient + text.
- Never resolve a person to a group chat (`--to` is 1:1 only).
- Groups need `--chat-guid` after the user named that group.

## Credits

Reminders-pattern inspiration: Federico Viticci / MacStories RemCTL — not vendored here.

## Privacy

Do not commit `~/.cache/grok-notes`, `chat.db`, contact dumps, or secrets.
