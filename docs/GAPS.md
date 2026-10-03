# Capability gaps (honest)

Updated 2026-10-03. Versions: grok-calendar 0.1.5, grok-contacts 0.1.2, grok-desk 0.1.7, grok-focus 0.1.1, grok-icloud 0.1.1, grok-mail 0.1.2, grok-messages 0.2.7, grok-notes 0.2.1, grok-reminders 0.1.4, grok-safari 0.1.1, grok-shortcuts 0.1.2, grok-spotlight 0.1.0. Measured doctors for Notes, Contacts, and Messages are the earlier same-day snapshot in AUDIT.md. Calendar, Reminders, and Mail doctors were not re-run. See SCOPE_AUDIT.md for the full Mac + iOS 27 map.

## Shipped limits

- Notes 0.2.1: no pin/lock/drawings/scans/tables/audio; checklist checked-state is flaky; tags are hashtags in the cache (`tags --folder` does not start a live search)
- Contacts 0.1.2: no phone or email search (`search --field phone|email` exits `unsupported_field` and does not call Contacts); no merge, photos, or vCard
- Messages 0.2.7: shipped mark-read, history, unread, and gated send. Plain-text send; `--to` is 1:1; groups need `--chat-guid`; `attachments` is metadata for one chat (no absolute path, no file open, no send). `mark-read` does not write `chat.db`.
- Calendar 0.1.5: Automation Allow still required; `show` can return recurrence plus attendee and alarm counts once Allow lands; create/update/delete have offline `--dry-run`
- Reminders 0.1.4: Automation Allow still required; `add --dry-run` validates the due format; `show` also reads remind-me date and all-day when Allow lands
- Mail 0.1.2: no send; draft `--dry-run` checks subject and `@`; doctor not retried
- Shortcuts 0.1.2: `run` needs `--force`; `--dry-run` only checks that the name is installed
- iCloud 0.1.1: CloudDocs only; `summary` counts local bytes and evicted files; no download
- Spotlight 0.1.0: paths only, Documents/Desktop by default; Keychains, Messages, Mail, HomeKit, Passes, Safari, Cookies refused
- Focus 0.1.1: best-effort status from the local Do Not Disturb database on macOS 27. `set` without `--force` refuses. `--force` still needs an existing `--shortcut` and does not write the database. No doctor loop.
- Safari 0.1.1: bookmarks and Reading List from Bookmarks.plist only. No history, passwords, cookies, edits, or URL opens. Unreadable plist exits `needs_full_disk_access` without opening System Settings.
- Desk 0.1.7: onboarding and local indexes. Contacts cache stays off unless requested.

## Deliberately not built

Notification Center, Maps, Find My, Screen Time, Continuity Camera, AirDrop, Freeform, Journal, Photos, Voice Memos, Weather store, Clock alarms, System Settings toggles, widgets, Lock Screen, Control Center, Stage Manager, Handoff, Universal Clipboard, iCloud Keychain, Wallet, HomeKit.

## Tapbacks v1 (not implemented)

Design only. `grok-messages react` is not shipped.

Dry-run prints the chat id, a likely last-message snippet, the reaction, and the exact command `imsg react --chat-id <rowid> --reaction <love|like|dislike|laugh|emphasis|question>`. `--force` runs that command once.

Wrap the `imsg` binary that implements `react` (source checkout `~/Developer/vendor/imsg`). Do not brew-install. Do not copy AppleScript. Do not call `imsg tapback`, `imsg launch`, or IMCore. `imsg react` hits the last-or-selected message, not a GUID. 1:1 only; v1 may refuse groups. No `chat.db` writes. Missing `imsg react` is a clean error, not an AppleScript fallback. `screen_locked` fails before UI.
