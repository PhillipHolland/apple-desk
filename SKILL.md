---
name: Apple Desk
description: >-
  Use when the user wants Apple Reminders, Calendar, Notes, Contacts,
  iMessage, Shortcuts, Apple Mail, iCloud Drive, a scoped Spotlight
  search, Focus status, or Safari bookmarks on their Mac: look up, organize, or draft.
  One skill for grok-reminders, grok-calendar, grok-notes, grok-contacts,
  grok-messages, grok-shortcuts, grok-mail, grok-icloud, grok-spotlight,
  grok-focus, and grok-safari.
  Not Google Calendar, not Passwords, not HomeKit, not cloud Apple APIs.
---
# Apple Desk

One skill for the Mac-local CLIs. Not a cloud connector. Run every command on the user's registered Mac (`machineId` on Shell / Read). Never on the cloud box. Never on a phone.

| Area | CLI | Version checked 2026-10-03 | Backend |
| --- | --- | --- | --- |
| Reminders | `grok-reminders` | 0.1.2 | Reminders.app JavaScript. In-house, not RemCTL. Pattern credit: Federico Viticci / MacStories. RemCTL is not a dependency. Hard 20–25s timeouts; blocked on Automation Allow. `add --dry-run` does not call Reminders |
| Calendar | `grok-calendar` | 0.1.2 | Calendar.app JavaScript (`osascript`). Read by default. Hard 20–25s timeouts; blocked on Automation Allow. create/update/delete `--dry-run` stays offline |
| Notes | `grok-notes` | 0.2.1 | Notes.app JavaScript (`osascript`). Search uses a local cache. `tags --folder` is cache-only |
| Contacts | `grok-contacts` | 0.1.1 | Contacts.app JavaScript. `search --field phone or email` is refused and does not call Contacts |
| iMessage | `grok-messages` | 0.2.1 | Messages.app JavaScript to send. `~/Library/Messages/chat.db` read-only for history and attachment metadata. Person send rules are under Agent rules |
| Shortcuts | `grok-shortcuts` | 0.1.1 | `/usr/bin/shortcuts`. List is safe. `run` does nothing without `--force`. `--dry-run` only checks the name |
| Spotlight | `grok-spotlight` | 0.1.0 | `/usr/bin/mdfind`. Paths only. Default scope is Documents and Desktop. Keychain, Messages, Mail, HomeKit, Safari, and Cookies paths are refused |
| Focus | `grok-focus` | 0.1.0 | Best-effort read of the local Do Not Disturb database on macOS 27. Does not write it. `set` needs `--force` and an existing `--shortcut` |
| Safari bookmarks | `grok-safari` | 0.1.0 | `~/Library/Safari/Bookmarks.plist` only. Bookmarks and Reading List. No history, passwords, edits, or URL opens |

Google calendars stay on the Google Calendar connector. `grok-calendar` only sees calendars already in Calendar.app. Prefer the Gmail connector for phillip.b.holland@gmail.com cloud mail; `grok-mail` is for Mail.app on this Mac. Passwords and HomeKit are out on purpose.

## When not to use

- No registered Mac, or the Mac is offline
- Safari history, passwords, cookies, or iCloud.com. Bookmarks and Reading List are `grok-safari` only. Photos, Freeform, Journal, FaceTime stay out
- Passwords, Keychain, or HomeKit. Do not probe them
- Raw `sqlite3` against NoteStore, AddressBook, or `chat.db`. Use the CLIs. Do not copy those databases off the Mac
- PyPI / GitHub `jwmoss/notesctl`. That is a different NoteStore exporter. Do not install it and do not name our binary `notesctl`

## Install

**Today (already on the office Mac):**

- `~/bin/grok-reminders` → `~/Developer/grok-reminders` (also `~/.local/bin`)
- `~/bin/grok-notes` → `~/Developer/grok-notes` (also `~/.local/bin`)
- `~/bin/grok-contacts` → `~/Developer/grok-contacts`
- `~/bin/grok-messages` → `~/Developer/grok-messages`
- `~/bin/grok-calendar` → `~/Developer/grok-calendar` (also `~/.local/bin`)
- `~/bin/grok-shortcuts` → `~/Developer/grok-shortcuts` (also `~/.local/bin`)
- `~/bin/grok-mail` → `~/Developer/grok-mail` (also `~/.local/bin`)
- `~/bin/grok-icloud` → `~/Developer/grok-icloud` (also `~/.local/bin`)
- `~/bin/grok-spotlight` → `~/Developer/grok-spotlight` (also `~/.local/bin`)
- `~/bin/grok-focus` → `~/Developer/grok-focus` (also `~/.local/bin`)
- `~/bin/grok-safari` → `~/Developer/grok-safari` (also `~/.local/bin`)

`~/bin/remctl` may still be on disk. Do not call it.

Those project folders are not git repos yet. No sudo.

**When Phillip shares a public GitHub URL (placeholder, do not invent one):**

1. Clone that repo to `~/Developer/apple-desk` (or the path its README names)
2. Symlink its reminders, notes, contacts, messages, calendar, and shortcuts binaries to `~/bin/` and `~/.local/bin/`
3. Do not copy the RemCTL binary or Capability Host into the public repo. Credit Viticci / MacStories as the pattern only
4. Re-run each `doctor` below. Do not commit `~/.cache/grok-notes`, `chat.db`, reminders stores, or contact exports
5. If `https://github.com/viticci/notesctl` becomes a real public repo, switch Notes to that official CLI and stop treating `grok-notes` as the long-term tool. Until then, `grok-notes` is the Notes path. Club MacStories beta is not installed and must not be fetched unless the user hands over the binary

## Agent rules

- Mac only. Pass `machineId`. One Apple Event-style command at a time. Do not parallelize writes, `--live` note search, or several Messages calls
- Read-only until the user asks to create, edit, complete, move, or delete
- Pass user text as CLI arguments. Do not interpolate titles, names, or message text into a hand-written AppleScript
- After a write, verify with a single `info` / `show` / `doctor` of that object
- Privacy: do not paste reminder bodies, note bodies, phones, emails, street addresses, handles, or message text into group chats, email, Slack, or posts unless the user just asked to share that specific item
- Phase 4 send rules (iMessage). Draft the recipient and the exact text, show that draft, and wait for an explicit yes before any send. `send` without `--force` must not be run. `--dry-run` never sends, even with `--force`. `--to` is a person (phone, email, or a 1:1 chat) and must never target a group, even if that handle is a member of one. The CLI sends a 1:1 Messages `participant`. If the handle exists only in a group, the CLI exits `refusing_group` and prints the group name and guid. Stop there. Do not retry with `--force`, do not pick that group yourself, and do not send. A group send is allowed only when the user named that group. Then use `--chat-guid` with the guid they confirmed, still only after they said yes to the exact text. Never pass a person's handle as `--to` hoping it lands in the right thread. If the match might be wrong, dry-run first and show route, style, guid, and service, not message text. Do not create `~/.config/grok-messages/allowlist` unless they asked for one. If that file exists, targets must match a line. Do not work around a refused send with the Messages UI or another tool
- Deletes need `--force` and an id (or an exact folder/group name the user gave). Never `empty-trash` unless they explicitly asked to empty Recently Deleted. Never `delete-folder --allow-large` or `delete-group --allow-large` unless they named that container and accepted the size. Calendar delete is one `--uid` plus `--force`. Never mass-delete events
- Exit **3** or **-1743** ("Not authorized to send Apple events"): stop. Do not loop. Tell them the Automation click for that app (Reminders, Calendar, Notes, Contacts, or Messages) under System Settings → Privacy & Security → Automation, for **Grok Bot** / **Grok Bot Helper**
- Calendar exit **3** with `calendar_tcc`, or events still empty after Automation is on: System Settings → Privacy & Security → Calendars → enable **Grok Bot** and **Grok Bot Helper**, then quit and reopen Grok Bot. One change, then `grok-calendar doctor` once
- Exit **4** or **-1712**: the app is busy or a prompt is up. Do not retry while Phillip is away. `grok-calendar`, `grok-reminders`, and `grok-mail` doctors timed out on 2026-10-03. After he says the dialog is handled, one `doctor` is enough
- Messages history exit **5** or `needs_full_disk_access`: send may still work. Ask them to turn on Full Disk Access for Grok Bot and Grok Bot Helper, then reopen Grok Bot. Do not copy `chat.db` somewhere else to get around it
- `not_in_messages_ui`: history sees the chat, Messages scripting does not. Do not retry with a different send API
- Locked notes: skip them. Never type or request the Notes password. `pin`, `unpin`, `lock`, and `unlock` are unsupported on purpose
- If `search` on notes returns `no_index`, run `reindex` once. Do not start with `--live`

## Capability matrix

Checked 2026-10-03. Notes, contacts, and messages doctors were ok around 12:45 PM CT. Calendar doctor ~12:58 PM CT and reminders doctor later that afternoon both exited 4. Do not rerun either until Phillip is back. Shortcuts list worked (35). No shortcut was run.

| Human can | This skill can | Cannot (do not fake it) |
| --- | --- | --- |
| Reminders lists, due dates, complete, delete | `grok-reminders`: lists, today, upcoming, search, show, add, done, delete one with `--force` | Smart lists, sections, tags, subtasks, recurrence, location alarms, move, flag writes, sharing, Recently Deleted. `remctl` is not the path. Doctor not green yet (exit 4, not retried) |
| Calendar.app calendars and events | List calendars, list events in a range (titles and times), search title/location, show one uid, create, update, delete one event with `--force` | Invites, RSVP, alarms, travel time, recurrence edits, moving an event to another calendar, mass delete. Google Calendar cloud. Passwords. HomeKit |
| Notes folders, text, checklists, search, trash | Folder tree, list, show, cached search (~0.08s here; 1215 notes), create/edit/append/rename/move, delete to Recently Deleted or permanent, folder delete, empty trash, list attachments, read shared flag, add an unchecked checklist row | Pin, lock, toggle a checkbox, duplicate, drawings, scans, tables, audio, attachment bytes, tag objects, smart folders, start a share or copy a collab link. `search --live` is the slow path (~30s). Writes do not update the cache until `reindex` |
| Contacts cards and groups | Counts, group names, search by name or organization, show one card, create/update/delete, labeled phone/email/url, group membership | Search by phone, email, or street (`search --field phone or email` exits `unsupported_field` and does not call Contacts). Merge or unlink. Photos, posters, Memoji. Smart lists, Medical ID, emergency contacts, vCard import/export. Group membership on `show` is skipped above 80 groups |
| Messages inbox, threads, send | Primary chat list, recent text in one named chat, text search, dry-run, plain-text 1:1 send via a Messages participant. Group send only with `--chat-guid` after the user named that group. `attachments` lists metadata for one chat (name, mime, bytes) | Sending `--to` a handle into a group that merely contains them. New chat, new group, sending or opening an attachment, tapbacks, stickers, effects, edit, unsend, reply, pin, mute, mark read. History for chats missing from the scripting list (often unknown senders). Attachment-only rows (null text). iCloud.com |
| Files on this Mac | `grok-spotlight search` returns paths under Documents and Desktop, or a folder you pass with `--onlyin` | File contents. Keychains, Messages, Mail, HomeKit, Passes, Safari, Cookies. Whole-disk search |
| Focus on this Mac | `grok-focus status` (best-effort: on/off and configured mode names) | Turning Focus on without `--force` and a shortcut the user already has. Writing the Do Not Disturb database. Notification Center. Assuming another device matches this Mac |
| Safari bookmarks and Reading List | `grok-safari bookmarks`, `reading-list`, and `search` from Bookmarks.plist, clipped by `--limit` | History, cookies, passwords, open tabs, editing bookmarks, opening URLs |

`grok-reminders gaps`, `grok-calendar gaps`, `grok-notes gaps`, `grok-contacts gaps`, `grok-messages gaps`, and `grok-shortcuts gaps` print the same limits. Trust those if they disagree with this table.

## Commands

```bash
grok-reminders doctor --json
grok-reminders lists --json
grok-reminders today --json
grok-reminders upcoming --days 7 --json
grok-reminders search "query" --json
grok-reminders show --id REMINDERID --json
grok-reminders add --title "Title" --list "ListName" --due "YYYY-MM-DD HH:MM" --priority high
grok-reminders done --id REMINDERID
grok-reminders delete --id REMINDERID --force
grok-reminders gaps
```

Due times are the Mac's local time (`YYYY-MM-DD` or `YYYY-MM-DD HH:MM`; a date with no clock is stored at 09:00). `today` and `upcoming` skip reminders with no due date and skip completed ones. `upcoming` is today through N days (1–60, default 7). `delete` is one id. Do not call `remctl`.

```bash
grok-calendar doctor --json
grok-calendar calendars --json
grok-calendar list --today --json          # default list is today through 7 days
grok-calendar list --from 2026-10-03 --to 2026-10-10 --limit 20 --json
grok-calendar search "standup" --days 14 --json
grok-calendar show --uid EVENTUID --json
grok-calendar create --calendar "Calendar" --title "Dentist" --start "2026-10-08 15:00" --end "2026-10-08 16:00"
grok-calendar update --uid EVENTUID --location "Office"
grok-calendar delete --uid EVENTUID --force
grok-calendar gaps --json
```

`list` prints titles and times only. Do not paste a full day into a shared channel. `show` adds location, notes, url, and recurrence for one uid they named. Search defaults to 30 days back through 180 ahead and matches title and location only. Create and update are the write commands. Delete is one event.

```bash
grok-notes doctor --json
grok-notes status --json
grok-notes reindex                        # incremental; --full rereads every body
grok-notes search "query" --limit 20 --json
grok-notes folders --json                 # --cached skips Apple Events
grok-notes list "Notes" --limit 20 --json
grok-notes show --id NOTEID --json        # or exact title; --full beyond 4000 chars
grok-notes tags --limit 30 --json
grok-notes tags --folder "Notes" --json   # cache only; does not start --live
grok-notes create-note --title "Title" --body "text" --folder "Folder" --account "iCloud"
grok-notes edit --id NOTEID --append "more"
grok-notes move --id NOTEID --to-folder "Folder"
grok-notes delete-note --id NOTEID --force
grok-notes delete-note --id NOTEID --force --permanent
```

Cache is `~/.cache/grok-notes/index.sqlite` (directory 0700, file 0600, this Mac only). `cache-clear` deletes the index, not the notes. Do not cat or upload it. `show` truncates at 4000 characters unless `--full`. Truncate again in the reply. `open --id` focuses Notes; only if they asked to see it on screen.

```bash
grok-shortcuts doctor
grok-shortcuts list
grok-shortcuts list --folders
grok-shortcuts run "Shortcut Name" --force
grok-shortcuts gaps
```

`list` and `doctor` never run a shortcut. `list --folders` lists folder names. `list --folder "Name"` lists shortcuts in that folder. This CLI does not call `shortcuts view` (that opens the app). `run` without `--force` exits 2. `run --dry-run` checks the name and does not run it. Do not pass `--force` unless the user named that shortcut and accepted its side effects.

```bash
grok-contacts doctor --json
grok-contacts groups --json               # list is an alias
grok-contacts search "Name" --limit 20 --json
grok-contacts show --id CONTACTID --json
grok-contacts create --first "Ada" --last "Lovelace" --phone "mobile:555-0100" --email "work:ada@example.com"
grok-contacts update --id CONTACTID --org "Analytical Engines"
grok-contacts delete --id CONTACTID --force
grok-contacts create-group "Engineers"
grok-contacts delete-group "Engineers" --force
```

`doctor` prints counts only, not the Me card's name or numbers. `search` needs at least 2 characters, matches name and organization only, and refuses more than 200 hits. `search --field phone` and `search --field email` exit `unsupported_field` without calling Contacts. `search` and `groups` do not include phones or emails. `show` does, for one id they named.

### Phase 4 — Messages send

Draft first. Show who (1:1 handle, or the group name plus guid) and the exact text. Wait for the user to say yes. Then:

```bash
grok-messages doctor --json
grok-messages chats --limit 30 --json     # primary inbox; list is an alias
grok-messages chats --query "Name" --json
grok-messages chats --filter unknown --limit 20 --json
grok-messages recent --to "+15551212" --limit 15 --json
grok-messages search "query" --to "Ada" --limit 15 --json
grok-messages send --help
grok-messages send --to "+15551212" --text "hello" --dry-run
grok-messages send --to "+15551212" --text "hello" --service iMessage --force
grok-messages send --chat-guid "GUID" --text "hello" --dry-run
grok-messages attachments --chat-guid "GUID" --limit 20 --json
```

`attachments` is read-only metadata (name, mime, bytes, sticker, date). It does not print the absolute path and does not open or send the file. Prefer `--chat-guid` when the chat might be a group.

`doctor` prints counts, not handles. `chats` has handles and counts, not message text. Summarize; do not dump the inbox. `recent` and `search` cap at 40 rows. Search needs 2 characters and refuses more than 500 hits. Read-side `--to` can still match a chat guid, phone (`+1` assumed for 10-digit US), email, or exact display name, which may be a group. Send-side `--to` is different: person or 1:1 only. It must not deliver into a group. `refusing_group` means stop and ask; the fix is `--chat-guid` only after they name the group. Ambiguous 1:1 matches exit 2 and list guid, service, and filter only.


```bash
grok-mail doctor --json
grok-mail accounts --json
grok-mail mailboxes --json
grok-mail list --mailbox INBOX --limit 10 --json
grok-mail search "query" --limit 10 --json
grok-mail show --id MSGID --json
grok-mail draft --to "a@b.com" --subject "S" --body "text"   # needs --force to create unsent
grok-mail gaps
```

`doctor` may exit 4 if Automation Allow is pending — do not retry while AFK. Prefer Gmail connector for cloud Gmail. `draft` without `--force` must not create anything. There is no `send` in 0.1.1. Do not paste full message bodies into shared channels.


```bash
grok-icloud doctor --json
grok-icloud ls --json --limit 50
grok-icloud tree --depth 1 --json
grok-icloud find "*.pdf" --limit 20 --json
grok-icloud cat "path/to/file.txt"
grok-icloud summary --depth 2 --json
grok-icloud gaps --json
```

CloudDocs only (`~/Library/Mobile Documents/com~apple~CloudDocs`). Evicted files report `evicted` and are not downloaded. No `--download`. `summary` totals local bytes and stops at a node cap; a capped summary is not the whole drive. Prefer Google Drive connector for Drive files.

```bash
grok-spotlight doctor --json
grok-spotlight search "query" --limit 20 --json
grok-spotlight search "report" --name --onlyin ~/Documents
grok-spotlight gaps --json
```

Spotlight returns paths, not file contents. Default scope is `~/Documents` and `~/Desktop`. Do not point `--onlyin` at Keychains, Messages, Mail, HomeKit, Safari, or Cookies; the CLI refuses those.

```bash
grok-focus doctor --json
grok-focus status --json
grok-focus set --mode "Do Not Disturb" --dry-run
grok-focus gaps --json
```

Focus status is best-effort on macOS 27 (local Do Not Disturb assertions only). Do not `set` without the user asking to change Focus. `--dry-run` never changes it. `--force` still requires `--shortcut` of an existing shortcut and does not write the database. Do not paste configured mode details into a shared channel unless they asked.

```bash
grok-safari doctor --json
grok-safari bookmarks --json --limit 20
grok-safari reading-list --json --limit 20
grok-safari search "query" --json --limit 20
grok-safari gaps --json
```

Safari reads Bookmarks.plist only. Do not open the URLs, do not edit bookmarks, and do not dump a full bookmark list into a shared channel. If doctor says `needs_full_disk_access`, stop. Do not open System Settings.

## Demo (safe)

1. `grok-reminders lists` or `today` once doctor is green. Do not paste reminder titles into a shared channel. If doctor exits 4, stop
2. Skip `grok-calendar doctor` until Phillip says the Automation dialog is handled (it already exited 4). Then list today or a short window. Titles and times only. No delete demo
3. `grok-notes doctor --json` then `grok-notes search "<query they asked>" --json`. `show` only an id they named
4. `grok-contacts doctor --json` then `groups` or a narrow `search`. Do not `show` phones unless they asked for that card
5. `grok-messages doctor --json` then `chats --limit 5`. Do not `recent` unless they named the chat. Send demo is `--dry-run` only
6. A write demo uses a throwaway object, then deletes that object with `--force`. No `empty-trash`. No real recipient. No calendar mass delete

## Permission clicks (only if doctor says unauthorized)

- Automation: System Settings → Privacy & Security → Automation → Grok Bot (and Grok Bot Helper) → Reminders, Calendar, Notes, Contacts, or Messages
- Calendar data, if Automation is on but events still fail: System Settings → Privacy & Security → Calendars → Grok Bot and Grok Bot Helper, then quit and reopen Grok Bot
- Messages history: System Settings → Privacy & Security → Full Disk Access → Grok Bot and Grok Bot Helper, then quit and reopen Grok Bot
- Reminders: Automation for Grok Bot / Grok Bot Helper → Reminders. Not the RemCTL Capability Host. A dialog may already be up from the 2026-10-03 doctor timeout. Do not prompt again until Phillip is back

## Connector rank

Extra Apple connectors, highest feasibility first. Voice Memos and anything voice-related are out. Calendar is built but its doctor is blocked. Shortcuts list works.

1. **Calendar** — built. `grok-calendar` via Calendar.app JXA. Automation, plus Calendars privacy if event data is still blocked. Ops: read, search, create, update, delete one. Fits the existing Automation click. Not the same grant as Reminders.
2. **Shortcuts** — built. `grok-shortcuts` 0.1.1 lists folders and can run. No Full Disk Access. `run` needs `--force` because a shortcut can change other apps. `--dry-run` does not run. Editing shortcut contents is not realistic. 35 shortcuts were listed earlier on 2026-10-03. None were run this pass.
3. **Spotlight** — built. `grok-spotlight` 0.1.0. Paths only. No new TCC for Documents, Desktop, or Developer.
3b. **Focus** — built read-only. `grok-focus` 0.1.0. Best-effort on macOS 27. Do not enable Focus unless the user asked and passed a shortcut.
3c. **Safari bookmarks** — built read-only. `grok-safari` 0.1.0. Bookmarks.plist only. No history.
4. **Mail** — built as spike. `grok-mail` 0.1.2: read/list/search/show + gated draft. No send. Hard 20–25s timeouts + body clip 800. Doctor timed out 2026-10-03 (~1:13 PM CT, exit 4). Do not retry until Allow. Prefer Gmail connector for cloud Gmail.
5. **Freeform** — Freeform.app scripting can open a board. Search and layout edits inside a board are mostly unsupported. Not built.
6. **Journal** — Journal.app has almost no AppleScript. The local store is TCC-walled. Do not scrape it. Not built.
7. **Photos** — Photos.app / PhotoKit. Separate Photos privacy. Libraries are huge and iCloud originals may be unloaded. Edits are destructive. Not built.
8. **HomeKit** — separate Home permission. Controlling accessories is a safety boundary. Do not touch.
9. **Passwords** — Keychain and Passwords. Do not touch.

Last verified on the office Mac, 2026-10-03: macOS 27.0, Notes 4.13, Contacts 14.0, Messages 26.0. Notes, contacts, and messages doctors were ok earlier. `grok-messages` 0.2.0: a person target that only matches a group returns `refusing_group`. A fixture and 35 real handles that also sit in groups resolved to a 1:1 or a refusal. No message was sent. `grok-calendar` doctor ~12:58 PM CT exited 4. `grok-reminders` 0.1.1 is installed (timeouts capped 20–25s); its first doctor timed out (exit 4) and was not retried. `grok-shortcuts` 0.1.0 listed 35 shortcuts; `run` without `--force` exited 2. Snapshot: `~/Developer/AUDIT.md` on that Mac.

`grok-mail` 0.1.2: draft `--dry-run` checks subject and `@` and does not call Mail. Earlier doctor exit 4 was not retried. Draft without --force exits needs_force.

Scope map: `docs/SCOPE_AUDIT.md` in the private apple-desk repo. `grok-focus` 0.1.0 and `grok-safari` 0.1.0 are read-only AFK spikes. Find My, Wallet, Journal, Photos, Voice Memos, Safari history, and Keychain stay out.
