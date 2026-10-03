# Onboard (guided Mac permissions)

Use this when a bot (or a human) is wiring Apple Desk on a Mac for the first time. One permission gate at a time. Why, then a doctor check. Stop on exit **3** or AppleEvent **-1743**. Do not loop doctors while AFK. Screen lock does not block non-UI commands (send participant path, history reads, lean doctors).

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

## Gate order

| # | Gate | Why | Check | On failure, open |
| --- | --- | --- | --- | --- |
| 1 | Full Disk Access (Messages history) | Read `chat.db` for history, unread, search. Send does **not** need FDA. | `grok-messages doctor` → history available | System Settings → Privacy & Security → Full Disk Access → enable **Grok Bot** and **Grok Bot Helper**, then quit and reopen Grok Bot |
| 2 | Automation → Messages | Send and scripting list | `grok-messages doctor` → automation authorized | System Settings → Privacy & Security → Automation → Grok Bot (and Grok Bot Helper) → **Messages** |
| 3 | Automation → Notes | Notes.app control | `grok-notes doctor` | … → Automation → **Notes** |
| 4 | Automation → Contacts | Live Contacts.app (cache-only doctor is not enough) | `grok-contacts doctor --live` | … → Automation → **Contacts** |
| 5 | Automation → Calendar | Calendar.app lean doctor | `grok-calendar doctor` | … → Automation → **Calendar**. If Automation is on but event data is still blocked: Privacy & Security → **Calendars** → Grok Bot / Grok Bot Helper, then reopen Grok Bot |
| 6 | Automation → Reminders | Reminders.app lean doctor | `grok-reminders doctor` | … → Automation → **Reminders** |
| 7 | Shortcuts | List shortcuts | `grok-shortcuts doctor` | Usually no extra TCC; if the CLI is missing, finish Install first |
| 8 | Mail (optional) | Mail.app on this Mac; prefer a cloud mail connector | version / one doctor attempt | … → Automation → **Mail**. Do not loop on exit 4 |
| 9 | iCloud Drive (optional) | CloudDocs list/read | `grok-icloud doctor` | Usually no dialog; missing folder is not FDA |
| 10 | Signature | Outgoing footer the **user** chooses | `grok-desk signature` | Ask once. Then `grok-desk signature --set "…"`. Never bake a default. `--clear` to unset |
| 11 | Reindex | Local caches under `~/.cache/grok-*` | `grok-desk reindex` | Fix any earlier `pending_allow` gate, then re-run guided |

## Exit codes the bot must honor

| Code / signal | Meaning | Bot action |
| --- | --- | --- |
| 0 | Gate or full guided pass | Continue or finish |
| 2 | Bad args / signature unset (guided stopped to ask) | Ask the user; do not invent a line |
| 3 / **-1743** | Not authorized to send Apple events | Print the Settings path from stdout/JSON. **Stop. Do not retry in a loop.** |
| 4 / **-1712** | Hang or dialog still up | Stop while AFK. After the user answers Allow (or unlocks), one retry |
| 5 | Needs Full Disk Access (Messages history) | Print FDA path. Send may still work |

## Messages send rules (preserve; generic)

- 1:1 send is Messages **participant** only. No `activate`, no menus.
- Draft recipient + exact text; wait for explicit yes; then `grok-messages send --force`. The CLI does **not** append the signature; the bot reads `grok-desk signature` and appends the line the user set.
- Exit 4 / -1712 on send: quit and relaunch Messages **once**, one send, then stop.
- Do not write `chat.db`. Read-only confirm of one outgoing row is ok after an approved send.
- Group send only with `--chat-guid` after the user named that group.
- `mark-read` is the only UI path; it exits `screen_locked` before activate when the screen is locked.

## Packaging note

Calendar and Reminders stay on the existing app CLIs (`grok-calendar`, `grok-reminders`). Do not block onboard on a new EventKit backend. Prefer wrapping public apple-pim / imsg patterns later; ship install + guided onboard first.
