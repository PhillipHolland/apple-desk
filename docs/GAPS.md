# Capability gaps (honest)

Updated 2026-10-03. Versions: grok-calendar 0.1.5, grok-contacts 0.1.3, grok-desk 0.1.7, grok-focus 0.1.1, grok-icloud 0.1.1, grok-mail 0.1.2, grok-messages 0.2.11, grok-notes 0.2.3, grok-reminders 0.1.4, grok-safari 0.1.2, grok-shortcuts 0.1.2, grok-spotlight 0.1.0. Measured doctors for Notes, Contacts, and Messages are the earlier same-day snapshot in AUDIT.md. Calendar, Reminders, and Mail doctors were not re-run. See SCOPE_AUDIT.md for the full Mac + iOS 27 map.

## Shipped limits

- Notes 0.2.3: `import-md` / `export-md` are a dry-run unless `--force`. `promote-checklist` reads one checklist line and adds one reminder through `grok-reminders add` only with `--force`. It does not mark the line done. A checked round-trip kept three heading sizes, lists, and simple pipe-table text. No pin/lock/drawings/scans/audio. Level-4 headings, quotes, footnotes, nested-list formatting, fence language, and image attachments are not preserved. Checklist checked-state is flaky. Tags are hashtags in the cache (`tags --folder` does not start a live search). Limits: `cli/grok-notes/README.md`.
- Contacts 0.1.3: phone, email, and relationship search use the index only (`--live` exits `unsupported_field` and does not call Contacts). `whose()` cannot filter related names. Nickname can use `--live`. `show` returns nickname and relationships already on the card. No merge, photos, or vCard
- Messages 0.2.11: shipped mark-read, history, unread, gated send, and 1:1 `react` (dry-run unless `--force`). Plain-text send; `--to` is 1:1; groups need `--chat-guid`. A missing 1:1 is created only when `--to` is a phone or email handle and the text is non-empty. The scripting dictionary cannot make an empty chat, so the first message is the creation, and only `--force` sends it. Dry-run does not send and does not create a chat. An existing 1:1 is reused. A display name with no 1:1 stays not found. `attachments` is metadata for one chat (no file open, no send). Default output has no absolute path. `--reveal-path` prints the stored local path and warns that it is a private file. It does not open or search the disk. `mark-read` does not write `chat.db`. `react` has no `--chat-guid` and refuses groups. `history` and `watch` wrap read-only imsg. Default is a dry-run and does not start imsg. `--force` still omits message text. imsg has no attachments subcommand; `original_path` prints only with `--reveal-path` and is not opened. `send` and `react` stay on their own gates. imsg search is still the in-house command.
- Calendar 0.1.5: Automation Allow still required; `show` can return recurrence plus attendee and alarm counts once Allow lands; create/update/delete have offline `--dry-run`
- Reminders 0.1.4: Automation Allow still required; `add --dry-run` validates the due format; `show` also reads remind-me date and all-day when Allow lands
- Mail 0.1.2: no send; draft `--dry-run` checks subject and `@`; doctor not retried
- Shortcuts 0.1.2: `run` needs `--force`; `--dry-run` only checks that the name is installed
- iCloud 0.1.1: CloudDocs only; `summary` counts local bytes and evicted files; no download
- Spotlight 0.1.0: paths only, Documents/Desktop by default; Keychains, Messages, Mail, HomeKit, Passes, Safari, Cookies refused
- Focus 0.1.1: best-effort status from the local Do Not Disturb database on macOS 27. `set` without `--force` refuses. `--force` still needs an existing `--shortcut` and does not write the database. No doctor loop.
- Safari 0.1.2: bookmarks and Reading List from Bookmarks.plist only. No history, passwords, cookies, Reading List edits, or URL opens. `to-note` is a dry-run unless `--force`; `--force` creates one Note through `grok-notes create-note` (title = item title, body = URL). Unreadable plist exits `needs_full_disk_access` without opening System Settings.
- Desk 0.1.7: onboarding and local indexes. Contacts cache stays off unless requested.

## Deliberately not built

Notification Center, Maps, Find My, Screen Time, Continuity Camera, AirDrop, Freeform, Journal, Photos, Voice Memos, Weather store, Clock alarms, System Settings toggles, widgets, Lock Screen, Control Center, Stage Manager, Handoff, Universal Clipboard, iCloud Keychain, Wallet, HomeKit.

## Tapbacks v1 (shipped)

`grok-messages react` is shipped. It stays 1:1 only, and it is a dry-run unless `--force`.

Dry-run prints the chat rowid, a short last non-reaction snippet, the reaction, and the exact command `imsg react --chat-id <rowid> --reaction <love|like|dislike|laugh|emphasis|question>`. `--force` does not pre-check the screen lock and does not activate Messages. It runs that command once. Vendor imsg react activates Messages itself and exits -2700 if Messages is not in front.

Wrap the `imsg` binary that implements `react` (`$GROK_MESSAGES_IMSG` when executable, else the source checkout `~/Developer/vendor/imsg` release binary). Do not brew-install. Do not copy AppleScript. Do not call `imsg tapback`, `imsg launch`, or IMCore. `imsg react` hits the last-or-selected message, not a GUID. Groups are refused (`refusing_group`). No `chat.db` writes. A missing binary is `missing_imsg` on `--force`, not an AppleScript fallback. Our wrap does not exit `screen_locked`. Vendor imsg still fails -2700 when Messages is not in front. The only non-UI tapback in that binary is imsg tapback, which injects IMCore and refuses to run while SIP is enabled. Apple Desk does not disable SIP, does not run imsg launch, and does not call imsg tapback. Locked-screen tapbacks are parked.
