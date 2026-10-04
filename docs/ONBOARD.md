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

## First win: unread digest

After gate 1 (Full Disk Access) and gate 2 (Automation → Messages) only. No other app is required.

```bash
grok-messages unread
```

The reply is counts: unread messages, unread chats, and a short page of chat labels. It does not print message text, and it does not mark anything read. Add `--json` for the same counts. If it exits 3, 4, 5, -1743, or -1712, follow the exit-code card once. Do not loop.

Later, after that app's own gate: `grok-notes search` (Notes) and `grok-reminders today` (Reminders).

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

Exit 0 means that gate passed. Exit 2 means bad arguments, or guided onboard stopped because the signature is unset: ask the user, and do not invent a line.

## Exit-code card

One failure, one human step, then stop. Do not loop the command.

| Code | Next human step |
| --- | --- |
| 3 | Open System Settings → Privacy & Security → Automation and turn on the named app for Grok Bot and Grok Bot Helper. Do not loop. |
- Send failures use the exit-code card. Exit **4** with an Allow dialog: click Allow once. Exit **4** with no dialog: quit Messages and open it once, then retry that same command once. Do not dig first. `--unstick-once` is off unless it was passed; then a timeout quits Messages, opens it once, and retries that same send once. It does not loop. An existing 1:1 is `sent: true` only after a read-only chat.db check sees a new outgoing row of that text. Otherwise the error is `send_unconfirmed` and `sent` is false.
- When send worked yesterday and hangs today, use the five-minute checklist in `docs/MESSAGES_SEND_HANG.md` before any long dig: quit and relaunch Messages, doctor, one dry-run, then one approved real send.

| 5 | Open System Settings → Privacy & Security → Full Disk Access, enable Grok Bot and Grok Bot Helper, then quit and reopen Grok Bot. Do not loop. |
| -1743 | Not authorized to send Apple events. Open the same Automation switch as exit 3 and click Allow once. Do not loop. |
| -1712 | Quit Messages and open it once, then retry that same command once. Do not loop. |
| screen_locked | Unlock the Mac, then retry mark-read once. Do not loop. Unread, doctor, and other non-UI commands are not blocked by the lock. |

## Messages send rules (preserve; generic)

- 1:1 send is Messages **participant** only. No `activate`, no menus.
- Draft recipient + exact text; wait for explicit yes; then `grok-messages send --force`. The CLI does **not** append the signature; the bot reads `grok-desk signature` and appends the line the user set.
- Send failures use the exit-code card. Exit **4** with an Allow dialog: click Allow once. Exit **4** with no dialog: quit Messages and open it once, then retry that same command once. Do not dig first. `--unstick-once` is the only automatic quit and relaunch, and it retries once. An existing 1:1 is not claimed sent until chat.db shows the new outgoing row (`send_unconfirmed` otherwise).
- Do not write `chat.db`. Read-only confirm of one outgoing row is ok after an approved send.
- Group send only with `--chat-guid` after the user named that group.
- `mark-read` is the only UI path; it exits `screen_locked` before activate when the screen is locked.

## Anonymous onboard count

After guided onboard exits 0, grok-desk may send one GET to `https://apple-desk-counter.vercel.app/onboard`. The same one-shot hit also runs the first time `grok-desk status` reports every probed doctor ok, if guided onboard never did. No query, no body, no identifiers. The CLI does not fail if the request fails. `GROK_DESK_NO_TELEMETRY=1` skips it. Read the total with `GET https://apple-desk-counter.vercel.app/count` (`{"count": N}`); that read does not increment.

## Packaging note

Calendar and Reminders stay on the existing app CLIs (`grok-calendar`, `grok-reminders`). Do not block onboard on a new EventKit backend. Prefer wrapping public apple-pim / imsg patterns later; ship install + guided onboard first.
