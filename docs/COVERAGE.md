# Coverage

Working-tree `--help` / `--version` on 2026-10-03. Any Mac. Not a release tag. Dirty trees from other writers are not product.

Messages `react` is the first peer wrap (`imsg react`, 1:1, dry-run unless `--force`). The other CLIs below are still in-house. Next step is wrap the remaining peer binaries and keep the `grok-*` name, the local `~/.cache/grok-*` cache, and the write gate. Do not vendor source.

## Bones

| CLI | Commands seen |
| --- | --- |
| `grok-desk` 0.1.7 | `doctor` `onboard` `reindex` `status` `search` `signature` `gaps` |
| `grok-messages` 0.2.10 | `doctor` `chats` `list` `recent` `search` `send` `attachments` `unread` `mark-read` `react` `gaps` |
| `grok-calendar` 0.1.5 | `doctor` `calendars` `name-at` `list` `search` `show` `create` `update` `delete` `gaps` |
| `grok-reminders` 0.1.4 | `doctor` `lists` `today` `upcoming` `search` `show` `add` `done` `delete` `gaps` |
| `grok-contacts` 0.1.3 | `doctor` `search` `show` `groups` `list` `create` `update` `delete` `create-group` `delete-group` `add-to-group` `remove-from-group` `gaps` |
| `grok-notes` 0.2.2 | `doctor` `folders` `list` `show` `search` `reindex` `status` `cache-clear` `tags` `create-note` `create-folder` `rename-folder` `delete-folder` `edit` `append` `move` `duplicate` `delete-note` `empty-trash` `attachments` `checklist` `share` `pin` `unpin` `lock` `unlock` `open` `import-md` `export-md` `gaps` |
| `grok-mail` 0.1.3 | `doctor` `accounts` `mailboxes` `list` `show` `search` `draft` `flag` `move` `mark-read` `gaps` |
| `grok-shortcuts` 0.1.2 | `doctor` `list` `create` `run` `gaps` |
| `grok-icloud` 0.1.1 | `doctor` `ls` `tree` `find` `cat` `summary` `gaps` |
| `grok-spotlight` 0.1.0 | `doctor` `search` `gaps` |
| `grok-focus` 0.1.1 | `doctor` `status` `modes` `set` `cache-clear` `gaps` |

`grok-desk reindex --only` is `notes|messages|contacts|calendar|reminders`. `grok-eventkit` is on disk and is not a bone (see in flight).

## Consent

- Messages `send`: draft the recipient and text, then `--force`. `--to` is 1:1. Groups only with `--chat-guid` after that group was named.
- Mail `draft` needs `--force` and does not send. `flag`, `move`, and `mark-read` are dry-run unless `--force` and do not send. Deletes and Focus `set` need `--force`.
- `mark-read` is shipped. It drives Messages (activate, then Conversation > Mark All as Read, or Mark as Read for one chat). It does not write `chat.db`. No IMCore. No SIP change.

## In flight (not done)

- EventKit for calendar and reminders (`grok-eventkit`, calendar/reminders helpers). Do not treat as shipped. Shipped calendar/reminders commands above are still the JXA CLIs.

## Tapbacks v1 (shipped)

`grok-messages react` is shipped. It stays 1:1 only, and it is a dry-run unless `--force`.

Dry-run prints the chat rowid, a short last non-reaction snippet, the reaction, and the exact command `imsg react --chat-id <rowid> --reaction <love|like|dislike|laugh|emphasis|question>`. `--force` does not pre-check the screen lock and does not activate Messages. It runs that command once. Vendor imsg react activates Messages itself and exits -2700 if Messages is not in front.

Wrap the `imsg` binary that implements `react` (`$GROK_MESSAGES_IMSG` when executable, else the source checkout `~/Developer/vendor/imsg` release binary). Do not brew-install. Do not copy AppleScript. Do not call `imsg tapback`, `imsg launch`, or IMCore. `imsg react` hits the last-or-selected message, not a GUID. Groups are refused. No `chat.db` writes. A missing binary is `missing_imsg` on `--force`, not an AppleScript fallback. Our wrap does not exit `screen_locked`. Vendor imsg still fails -2700 when Messages is not in front. The only non-UI tapback in that binary is imsg tapback, which injects IMCore and refuses to run while SIP is enabled. Apple Desk does not disable SIP, does not run imsg launch, and does not call imsg tapback. Locked-screen tapbacks are parked.

## Wrap (do not keep reinventing)

| Peer feature | Now | Next |
| --- | --- | --- |
| imsg `chats` `history` `search` `watch` attachment paths | Reimplemented: `chats` `list` `recent` `search` `unread`; `attachments` is metadata only | Wrap `imsg` for those reads. Keep our send gate. |
| imsg `send` (text and file) | Reimplemented: plain-text `send` only | Do not wrap file send until the same draft+yes gate exists. Reactions are Tapbacks v1: shipped 1:1 `react`, dry-run unless `--force`. |
| imsg RPC, scheduled, chat background, IMCore/SIP | Not shipped | Deferred. IMCore/SIP is not a product path. Tapbacks do not call these. |
| apple-tools `apple status` plus notes, mail, messages, contacts, reminders, calendar reads (MIT) | Reimplemented as `grok-desk status` and the JXA/cache CLIs | Wrap the MIT binaries behind `grok-*`. Their SQLite reads are the fast path. |
| apple-tools phone recents; mail body search; contact phone/email search and vCard; notes export | Missing from our commands (`search --field phone\|email` is a known gap) | Wrap apple-tools. Do not write a second reader. |
| apple-tools maps / geocode | Not shipped | Deferred. Geocode is a network call. |
| apple-pim `calendar-cli` / `reminder-cli` (EventKit, MIT): list, events, get, search, CRUD, recurrence, batch | Reimplemented in JXA. EventKit rewrite is in flight, not a wrap | Wrap `calendar-cli` and `reminder-cli`. Stop the second Swift tree when this pass lands. |
| apple-pim `contacts-cli` search by phone/email, birthdays | Reimplemented name search and group edits | Wrap `contacts-cli`. |
| apple-pim `mail-cli` envelope-index reads, attachments on disk | Reimplemented: subjects via Mail.app; `draft` only | Wrap the read-only SQLite path. Do not wrap `send`, `reply`, or `smtp-send`. |
| openclaw-apple-calendar `list` `events` `read` `search` `create` `update` `delete` | Same JXA surface as `grok-calendar` | Prefer one EventKit wrap (apple-pim or this plugin), not both plus `grok-eventkit`. |

## Deferred (not prod)

Passwords, HomeKit, Photos, Freeform, and Safari. `grok-safari` 0.1.2 exists (`doctor` `status` `bookmarks` `reading-list` `search` `to-note` `reindex`) and is still not a full product surface. Also out: Notification Center, Maps, Find My, Screen Time, Journal, Voice Memos, Weather, Clock, Wallet, and Settings toggles.

## Gaps

1. No peer binary is wrapped. Calendar, reminders, contacts, mail, and notes are still in-house.
2. Wrap `imsg` for history, watch, search, and attachment paths. Keep send gated.
3. Wrap apple-tools (MIT) for notes, mail, messages, contacts, phone, and `apple status`.
4. Wrap apple-pim EventKit (`calendar-cli`, `reminder-cli`) instead of growing `grok-eventkit`.
5. Pick one of apple-pim or openclaw-apple-calendar for event CRUD. Do not ship three backends.
6. `mark-read` is shipped (Messages UI: activate, then Mark as Read). It does not write `chat.db`.
7. Missing vs peers: phone recents, mail body search, contact phone/email search, vCard, attachment file paths.
8. Do not ship imsg file send or RPC without the draft+yes gate. Tapbacks v1 (`grok-messages react`) is shipped as a 1:1 dry-run/`--force` wrap of `imsg react`.
9. Passwords, HomeKit, Safari, Photos, and Freeform stay out of prod.
10. apple-tools maps/geocode and apple-pim SMTP send stay deferred.
