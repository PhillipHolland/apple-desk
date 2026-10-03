# Apple Desk

Mac-local Apple ecosystem tools for Grok Bot / agents: Reminders, Notes, Contacts, Messages, Calendar (and more), plus a planned single MCP server.

**Status:** private WIP. Keep this repo private until release.

## CLIs (under `cli/`)

| CLI | Role |
| --- | --- |
| `grok-reminders` | Reminders (in-house; RemCTL optional inspiration only) |
| `grok-notes` | Notes.app + search cache |
| `grok-contacts` | Contacts.app |
| `grok-messages` | Messages send (gated) + chat.db history |
| `grok-calendar` | Calendar.app |
| `grok-shortcuts` | Shortcuts list/run |

Install bins onto `~/bin` from each `cli/*/bin/` entrypoint. Requires macOS Automation (and Full Disk Access for Messages history).

## Hard rules (Messages)

- Never send without user pre-approval of recipient + text.
- Never resolve a person to a group chat.
- Prefer 1:1 participant sends.

## Credits

Reminders-pattern inspiration: Federico Viticci / MacStories RemCTL — not vendored here.

## Privacy

Do not commit `~/.cache/grok-notes`, `chat.db`, contact dumps, or secrets.
