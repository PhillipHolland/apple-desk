# Coverage

Working-tree `--help` / `--version` on 2026-10-03. Any Mac. Not a release tag. Dirty trees from other writers are not product.

Nothing below is an OSS wrap yet. Current CLIs are in-house. Next step is wrap the peer binary and keep the `grok-*` name, the local `~/.cache/grok-*` cache, and the write gate. Do not vendor source.

## Bones

| CLI | Commands seen |
| --- | --- |
| `grok-desk` 0.1.5 | `doctor` `onboard` `reindex` `status` `search` `signature` `gaps` |
| `grok-messages` 0.2.6 | `doctor` `chats` `list` `recent` `search` `send` `attachments` `unread` `mark-read` `gaps` |
| `grok-calendar` 0.1.7 | `doctor` `calendars` `name-at` `list` `search` `show` `create` `update` `delete` `gaps` |
| `grok-reminders` 0.1.5 | `doctor` `lists` `today` `upcoming` `search` `show` `add` `done` `delete` `gaps` |
| `grok-contacts` 0.1.2 | `doctor` `search` `show` `groups` `list` `create` `update` `delete` `create-group` `delete-group` `add-to-group` `remove-from-group` `gaps` |
| `grok-notes` 0.2.1 | `doctor` `folders` `list` `show` `search` `reindex` `status` `cache-clear` `tags` `create-note` `create-folder` `rename-folder` `delete-folder` `edit` `append` `move` `duplicate` `delete-note` `empty-trash` `attachments` `checklist` `share` `pin` `unpin` `lock` `unlock` `open` `gaps` |
| `grok-mail` 0.1.2 | `doctor` `accounts` `mailboxes` `list` `show` `search` `draft` `gaps` |
| `grok-shortcuts` 0.1.2 | `doctor` `list` `create` `run` `gaps` |
| `grok-icloud` 0.1.1 | `doctor` `ls` `tree` `find` `cat` `summary` `gaps` |
| `grok-spotlight` 0.1.0 | `doctor` `search` `gaps` |
| `grok-focus` 0.1.1 | `doctor` `status` `modes` `set` `cache-clear` `gaps` |

`grok-desk reindex --only` is `notes|messages|contacts|calendar|reminders`. `grok-eventkit` is on disk and is not a bone (see in flight).

## Consent

- Messages `send`: draft the recipient and text, then `--force`. `--to` is 1:1. Groups only with `--chat-guid` after that group was named.
- Mail `draft` needs `--force` and does not send. Deletes and Focus `set` need `--force`.
- `mark-read` must drive Messages (activate, then Conversation > Mark All as Read, or Mark as Read for one chat). It must not write `chat.db`. No IMCore. No SIP change.

## In flight (not done)

- EventKit for calendar and reminders (`grok-eventkit`, calendar/reminders helpers). Do not treat as shipped. Shipped calendar/reminders commands above are still the JXA CLIs.
- `grok-messages mark-read --all --force`: activate Messages, then click Mark All as Read only if that item is enabled. Activate alone is not success. Phone badge is not verified from the Mac.

## Wrap (do not keep reinventing)

| Peer feature | Now | Next |
| --- | --- | --- |
| imsg `chats` `history` `search` `watch` attachment paths | Reimplemented: `chats` `list` `recent` `search` `unread`; `attachments` is metadata only | Wrap `imsg` for those reads. Keep our send gate. |
| imsg `send` (text and file) | Reimplemented: plain-text `send` only | Do not wrap file send or reactions until the same draft+yes gate exists. |
| imsg RPC, reactions, scheduled, chat background, IMCore/SIP | Not shipped | Deferred. IMCore/SIP is not a product path. |
| apple-tools `apple status` plus notes, mail, messages, contacts, reminders, calendar reads (MIT) | Reimplemented as `grok-desk status` and the JXA/cache CLIs | Wrap the MIT binaries behind `grok-*`. Their SQLite reads are the fast path. |
| apple-tools phone recents; mail body search; contact phone/email search and vCard; notes export | Missing from our commands (`search --field phone\|email` is a known gap) | Wrap apple-tools. Do not write a second reader. |
| apple-tools maps / geocode | Not shipped | Deferred. Geocode is a network call. |
| apple-pim `calendar-cli` / `reminder-cli` (EventKit, MIT): list, events, get, search, CRUD, recurrence, batch | Reimplemented in JXA. EventKit rewrite is in flight, not a wrap | Wrap `calendar-cli` and `reminder-cli`. Stop the second Swift tree when this pass lands. |
| apple-pim `contacts-cli` search by phone/email, birthdays | Reimplemented name search and group edits | Wrap `contacts-cli`. |
| apple-pim `mail-cli` envelope-index reads, attachments on disk | Reimplemented: subjects via Mail.app; `draft` only | Wrap the read-only SQLite path. Do not wrap `send`, `reply`, or `smtp-send`. |
| openclaw-apple-calendar `list` `events` `read` `search` `create` `update` `delete` | Same JXA surface as `grok-calendar` | Prefer one EventKit wrap (apple-pim or this plugin), not both plus `grok-eventkit`. |

## Deferred (not prod)

Passwords, HomeKit, Photos, Freeform, and Safari. `grok-safari` exists (`doctor` `status` `bookmarks` `reading-list` `search` `reindex`) and is still not a product surface. Also out: Notification Center, Maps, Find My, Screen Time, Journal, Voice Memos, Weather, Clock, Wallet, and Settings toggles.

## Gaps

1. No peer binary is wrapped. Calendar, reminders, contacts, mail, and notes are still in-house.
2. Wrap `imsg` for history, watch, search, and attachment paths. Keep send gated.
3. Wrap apple-tools (MIT) for notes, mail, messages, contacts, phone, and `apple status`.
4. Wrap apple-pim EventKit (`calendar-cli`, `reminder-cli`) instead of growing `grok-eventkit`.
5. Pick one of apple-pim or openclaw-apple-calendar for event CRUD. Do not ship three backends.
6. `mark-read` is in flight (activate, then Mark All as Read). Not done. Not `chat.db`.
7. Missing vs peers: phone recents, mail body search, contact phone/email search, vCard, attachment file paths.
8. Do not ship imsg file send, reactions, or RPC without the draft+yes gate.
9. Passwords, HomeKit, Safari, Photos, and Freeform stay out of prod.
10. apple-tools maps/geocode and apple-pim SMTP send stay deferred.
