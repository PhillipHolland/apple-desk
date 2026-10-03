# Onboard (guided Mac permissions)

Use this when a bot (or a human) is wiring Apple Desk on a Mac for the first time. One permission gate at a time. Why, then a doctor check. Honor the exit-code card below. Do not loop doctors while AFK.

## Command

```bash
grok-desk onboard --guided
# JSON for agents:
grok-desk onboard --guided --json
# Opt in to contacts phone/email cache during the final reindex:
grok-desk onboard --guided --index-contacts
```

Plain `grok-desk onboard` still links missing bins, runs the short safe doctor rollup, and reindexes. `--guided` is the bot-friendly walk that **stops at the first failing gate** and prints the exact System Settings path.

Re-run the same command after the user clicks Allow. Passing gates are skipped. There is no AFK retry loop inside the command.

## First win (after the minimum gate only)

- `grok-messages unread` (Full Disk Access + Messages automation)
- `grok-notes search` (Notes automation)
- `grok-reminders today` (Reminders automation)

## Gate order

| # | Gate | Why | Check | On failure, open |
| --- | --- | --- | --- | --- |
| 1 | Full Disk Access (Messages history) | Read `chat.db` for history, unread, search. Send does **not** need FDA. | `grok-messages doctor` → history available | System Settings → Privacy & Security → Full Disk Access → enable **Grok Bot** and **Grok Bot Helper**, then quit and reopen Grok Bot |
| 2 | Automation → Messages | Send and scripting list | `grok-messages doctor` → automation authorized | System Settings → Privacy & Security → Automation → Grok Bot (and Grok Bot Helper) → **Messages** |
| 3 | Automation → Notes | Notes.app control | `grok-notes doctor` | … → Automation → **Notes** |
| 4 | Automation → Contacts | Live Contacts.app (cache-only doctor is not enough) | `grok-contacts doctor --live` | … → Automation → **Contacts** |
| 5 | Automation → Calendar | Calendar.app lean doctor | `grok-calendar doctor` | … → Automation → **Calendar**. Calendar may also need Privacy & Security → **Calendars** |
| 6 | Automation → Reminders | Reminders.app lean doctor | `grok-reminders doctor` | … → Automation → **Reminders**. Reminders may also need Privacy & Security → **Reminders** |
| 7 | Shortcuts | List shortcuts | `grok-shortcuts doctor` | Usually no extra TCC; if the CLI is missing, finish Install first |
| 8 | Mail (optional) | Mail.app on this Mac; prefer a cloud mail connector | version / one doctor attempt | … → Automation → **Mail**. Do not loop on exit 4 |
| 9 | iCloud Drive (optional) | CloudDocs list/read | `grok-icloud doctor` | Usually no dialog; missing folder is not FDA |
| 10 | Signature | Outgoing footer the **user** chooses | `grok-desk signature` | Ask once. Then `grok-desk signature --set "…"`. Never bake a default. `--clear` to unset |
| 11 | Reindex | Local caches under `~/.cache/grok-*` | `grok-desk reindex` | Fix any earlier `pending_allow` gate, then re-run guided |

Calendar and Reminders may also need Privacy & Security → Calendars or Reminders.

## Exit codes the bot must honor

| Code / signal | Meaning | Bot action |
| --- | --- | --- |
| 0 | Gate or full guided pass | Continue or finish |
| 2 | Bad args / signature unset (guided stopped to ask) | Ask the user; do not invent a line |
| 3, -1743 | Not authorized to send Apple events | Stop and open the Settings path. No loop. |
| 4 | Automation dialog still up | Stop for one Allow click. |
| 5 | Needs Full Disk Access (Messages history) | Full Disk Access. |
| -1712 | Messages hang on send | Quit and relaunch Messages once, then one send, then stop. |
| screen_locked | Screen is locked before UI | Unlock, then one retry. Never loop. |

## Messages send rules (preserve; generic)

- 1:1 send is Messages **participant** only. No `activate`, no menus.
- Draft recipient + exact text; wait for explicit yes; then `grok-messages send --force`. The CLI does **not** append the signature; the bot reads `grok-desk signature` and appends the line the user set.
- Send failures use the exit-code card: **4** stops for one Allow click; **-1712** quits and relaunches Messages once, then one send, then stop.
- Do not write `chat.db`. Read-only confirm of one outgoing row is ok after an approved send.
- Group send only with `--chat-guid` after the user named that group.
- `mark-read` is the only UI path; it exits `screen_locked` before activate when the screen is locked.

## Packaging note

Calendar and Reminders stay on the existing app CLIs (`grok-calendar`, `grok-reminders`). Do not block onboard on a new EventKit backend. Prefer wrapping public apple-pim / imsg patterns later; ship install + guided onboard first.
