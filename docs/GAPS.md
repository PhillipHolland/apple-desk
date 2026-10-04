# Capability gaps (honest)

Combined build 0.2.0. Mail, Calendar, and Desk are updated; other surfaces retain their own versions. Historical reports in AUDIT.md and SCOPE_AUDIT.md describe the machine and build used at that time, not current permission status. Use passive `apple-desk doctor` for the current Mail/Calendar authorization report.

## Shipped limits

- Notes 0.2.1: no pin/lock/drawings/scans/tables/audio; checklist checked-state is flaky; tags are hashtags in the cache (`tags --folder` does not start a live search)
- Contacts 0.1.2: no phone or email search (`search --field phone|email` exits `unsupported_field` and does not call Contacts); no merge, photos, or vCard
- Messages 0.2.8: shipped mark-read, history, unread, gated send, and 1:1 `react` (dry-run unless `--force`). Plain-text send; `--to` is 1:1; groups need `--chat-guid`; `attachments` is metadata for one chat (no absolute path, no file open, no send). `mark-read` does not write `chat.db`. `react` has no `--chat-guid` and refuses groups.
- Calendar 0.2.0: requires EventKit Full Access; attendee/RSVP writes are unsupported. Offline dry runs do not verify target existence or calendar writability. Write verification checks the local store, not remote account synchronization.
- Reminders 0.1.4: Automation Allow still required; `add --dry-run` validates the due format; `show` also reads remind-me date and all-day when Allow lands
- Mail 0.2.0: Mail.app Automation; bounded search with anchored cursors is not a transactional snapshot. Body limits cap output, not retrieval. Plain-text drafts and explicit idempotent sends; no HTML, permanent deletion, or delivery confirmation. Archive/trash need explicit destinations.
- Shortcuts 0.1.2: `run` needs `--force`; `--dry-run` only checks that the name is installed
- iCloud 0.1.1: CloudDocs only; `summary` counts local bytes and evicted files; no download
- Spotlight 0.1.0: paths only, Documents/Desktop by default; Keychains, Messages, Mail, HomeKit, Passes, Safari, Cookies refused
- Focus 0.1.1: best-effort status from the local Do Not Disturb database on macOS 27. `set` without `--force` refuses. `--force` still needs an existing `--shortcut` and does not write the database. No doctor loop.
- Safari 0.1.1: bookmarks and Reading List from Bookmarks.plist only. No history, passwords, cookies, edits, or URL opens. Unreadable plist exits `needs_full_disk_access` without opening System Settings.
- Desk 0.2.0: passive onboarding; indexing is explicit. Calendar indexes have a bounded window, freshness and coverage. Contacts collection remains opt-in. Live Calendar commands do not use the cache.

## Deliberately not built

Notification Center, Maps, Find My, Screen Time, Continuity Camera, AirDrop, Freeform, Journal, Photos, Voice Memos, Weather store, Clock alarms, System Settings toggles, widgets, Lock Screen, Control Center, Stage Manager, Handoff, Universal Clipboard, iCloud Keychain, Wallet, HomeKit.

## Tapbacks v1 (shipped)

`grok-messages react` is shipped. It stays 1:1 only, and it is a dry-run unless `--force`.

Dry-run prints the chat rowid, a short last non-reaction snippet, the reaction, and the exact command `imsg react --chat-id <rowid> --reaction <love|like|dislike|laugh|emphasis|question>`. `--force` does not pre-check the screen lock and does not activate Messages. It runs that command once. Vendor imsg react activates Messages itself and exits -2700 if Messages is not in front.

Wrap the `imsg` binary that implements `react` (`$GROK_MESSAGES_IMSG` when executable, else the source checkout `~/Developer/vendor/imsg` release binary). Do not brew-install. Do not copy AppleScript. Do not call `imsg tapback`, `imsg launch`, or IMCore. `imsg react` hits the last-or-selected message, not a GUID. Groups are refused (`refusing_group`). No `chat.db` writes. A missing binary is `missing_imsg` on `--force`, not an AppleScript fallback. Our wrap does not exit `screen_locked`. Vendor imsg still fails -2700 when Messages is not in front. The only non-UI tapback in that binary is imsg tapback, which injects IMCore and refuses to run while SIP is enabled. Apple Desk does not disable SIP, does not run imsg launch, and does not call imsg tapback. Locked-screen tapbacks are parked.
