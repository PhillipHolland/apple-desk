# Apple Desk scope audit

Checked 2026-10-03 about 1:40 PM CT on the office Mac (macOS 27.0, build 26A5388g).
No Messages or Mail were sent. No Automation dialogs were clicked. Calendar, Reminders, and Mail doctors were not re-run (they already timed out earlier the same day). Contacts phone `whose()` was probed once and failed fast with error -2700; it did not print cards.

This file is a capability map. It does not include message text, phone numbers, emails, note bodies, or file names from iCloud or Messages.

## What shipped before this pass

| Area | CLI | Then |
| --- | --- | --- |
| Notes | grok-notes 0.2.0 | JXA + local cache. Doctor was green. |
| Contacts | grok-contacts 0.1.0 | JXA. Name search only. Doctor was green. |
| Messages | grok-messages 0.2.0 | chat.db history + gated 1:1 send. |
| Calendar | grok-calendar 0.1.1 | JXA. Doctor exit 4, not retried. |
| Reminders | grok-reminders 0.1.1 | JXA. Doctor exit 4, not retried. |
| Shortcuts | grok-shortcuts 0.1.0 | `shortcuts list`. `run` needs `--force`. |
| Mail | grok-mail 0.1.1 | JXA read + gated draft. Doctor exit 4, not retried. |
| iCloud Drive | grok-icloud 0.1.0 | CloudDocs list/read. No download. |

## Each existing CLI

### grok-notes (now 0.2.2)

Commands: `doctor`, `gaps`, `folders`, `list`, `show`, `search` (cache, or slow `--live`), `reindex`, `status`, `cache-clear`, `tags`, `create-note`, `create-folder`, `rename-folder`, `delete-folder`, `edit`, `append`, `move`, `duplicate`, `delete-note`, `empty-trash`, `attachments`, `checklist show|add`, `share`, `pin`/`unpin`/`lock`/`unlock` (exit unsupported), `open`, `import-md`, `export-md`.

`import-md` and `export-md` are a dry-run unless `--force`. They convert a Markdown subset through Notes HTML. File > Import Markdown and File > Export To > Markdown are not in the scripting dictionary. Limits are in `cli/grok-notes/README.md`.

Feasibility: Notes.app JXA is the right layer on macOS 27. NoteStore.sqlite stays out. Hashtags are text, not tag objects.

Security: cache is `~/.cache/grok-notes` mode 0700. `--live` walks Notes and is slow. `open` focuses the app. Deletes need `--force`.

Top 5 still scriptable and missing:

1. Toggle a checklist row (HTML rewrite is flaky; not faked).
2. Duplicate is present; a true "copy as new" that preserves checklist state is still weak.
3. Attachment bytes (list only today).
4. Share-link read, not just a shared flag.
5. Account-scoped folder create when several iCloud accounts exist.

This pass: `tags --folder` filters the cache. No live search was run.

### grok-contacts (now 0.1.1)

Commands: `doctor`, `search`, `show`, `groups` / `list`, `create`, `update`, `delete`, `create-group`, `delete-group`, `add-to-group`, `remove-from-group`, `gaps`.

Feasibility: Contacts.app Apple Events, not CNContactStore (no usage-description prompt for a CLI). Name `whose()` works. Phone `whose()` does not: tested 2026-10-03, `people.whose({phones:…})` raises -2700 "Object does not have property phones". A full walk was timed at about 70 ms per card (40 cards in 2.8 s, 3245 cards on this Mac), which would take several minutes and load every number into the scripting process. Spotlight indexes only a slice of contacts (68 `public.contact` items, not the book).

Security: `search` and `groups` do not print phones. `show` does, for one id. No vCard dump.

Top 5 scriptable later, not this pass:

1. Phone/email search only after an explicit local index the user asks to build (0600, last-4 or exact, not a chat dump).
2. vCard export of one id.
3. Photo presence flag without the image bytes.
4. Birthday field already returned on `show`; a birthday query is the same walk problem as phones.
5. Merge/unlink is a poor JXA fit. Defer.

This pass: `search --field phone|email` exits `unsupported_field` and does not call Contacts.

### grok-messages (now 0.2.1)

Commands: `doctor`, `chats` / `list`, `recent`, `search`, `send` (`--force`, `--dry-run`, `--to` is 1:1, groups need `--chat-guid`), `attachments`, `gaps`.

Feasibility: send is Messages.app JXA. History is read-only `chat.db` (Full Disk Access already working for this agent). Attachment rows exist (`attachment`, `message_attachment_join`).

Security: `attachments` returns id, display name, mime, uti, bytes, outgoing, sticker, hidden, time, and whether a file path is stored. It does not return the absolute path, message text, or sticker blobs, and it does not open the file. Send rules are unchanged. Nothing was sent. A metadata check on one busy chat reported 801 attachment rows and returned 8 mime types only.

Top 5 still missing:

1. Send a file (do not add without a second human gate).
2. Tapback / reaction send.
3. Mark read, pin, mute.
4. Create a new 1:1 chat when scripting has no chat yet.
5. Edit / unsend (Messages scripting does not expose these honestly).

### grok-calendar (now 0.1.2)

Commands: `doctor`, `calendars`, `list`, `search`, `show`, `create`, `update`, `delete`, `gaps`. Create already had `--dry-run`. Update and delete do too.

Feasibility: Calendar.app JXA. EventKit from a CLI has the same TCC problem as Contacts. Doctor is blocked on Automation Allow. Code was not executed against Calendar.app this pass.

Security: dry-run validates `YYYY-MM-DD` or `YYYY-MM-DD HH:MM` and rejects an end before a start without calling Calendar. Delete dry-run does not need `--force` and does not delete.

`show` now also asks for `recurrence` (summary plus frequency/until when the object exposes them), `attendeeCount`, and `alarmCount`. It still does not list attendees or send invites.

Top 5 when Allow lands:

1. Create/edit a recurrence rule (read is ready; write is not).
2. Add one display alarm.
3. Move an event to another calendar.
4. RSVP / attendee names (count only today, on purpose).
5. Conference URL parse from notes (url is already returned when Calendar exposes it).

### grok-reminders (now 0.1.2)

Commands: `doctor`, `lists`, `today`, `upcoming`, `search`, `show`, `add`, `done`, `delete`, `gaps`.

Feasibility: Reminders.app JXA. Not RemCTL. Doctor blocked. `add --dry-run` checks the due format and does not call Reminders.

`show` now also reads `remindMeDate` and `allDay` on the matched reminder only (not on every list scan).

Top 5 when Allow lands:

1. Recurrence.
2. Subtasks.
3. Lists sections and tags.
4. Move between lists.
5. Location alarms (privacy-sensitive; defer even after Allow unless asked).

### grok-shortcuts (now 0.1.1)

Commands: `doctor`, `list` (`--folders`, `--folder`, `--show-identifiers`), `run` (`--force` or `--dry-run`), `gaps` (`--json`).

Feasibility: `/usr/bin/shortcuts` is the supported meta layer. `shortcuts view` opens the app; this CLI does not call it. `list --folder` is the folder view. `run --dry-run` checks the name against `shortcuts list` and does not run.

Security: a shortcut can send, call, or toggle Home. The wrapper cannot see the graph. `--force` stays mandatory.

Top 5 missing:

1. Sign or import a `.shortcut` file (possible, easy to misuse).
2. Pass stdin text, not only `--input-path`.
3. Folder identifiers without dumping every shortcut.
4. Per-shortcut "does this message anyone?" static analysis. Hard. Do not pretend.
5. Focus toggles implemented as shortcuts the user already has. Run still needs `--force`.

### grok-mail (now 0.1.2)

Commands: `doctor`, `accounts`, `mailboxes`, `list`, `search`, `show`, `draft` (`--force` or `--dry-run`), `gaps`. No `send`.

Feasibility: Mail.app JXA. Doctor blocked. Dry-run now requires a subject and an `@` in each `--to`, and does not call Mail.

`show`/`list` summaries now also include junk and replied flags (code only until Allow).

Top 5 when Allow lands:

1. Move / flag / mark read (scriptable, still a write).
2. Attachment names on one message, not bytes.
3. Mailbox unread already on mailbox list; a global unread digest.
4. Rules read-only.
5. Send. Still never. Prefer the Gmail connector for cloud mail.

### grok-icloud (now 0.1.1)

Commands: `doctor`, `ls`, `tree`, `find`, `cat`, `summary`, `gaps` (`--json`).

Feasibility: the CloudDocs folder on disk. No `brctl` download. `summary` sums local bytes, counts evicted placeholders, and stops at a node cap. A depth-1 cap of 200 nodes on this Mac returned totals only in the test (2 local files, 102 evicted, 93 directories in that partial walk).

Security: paths outside CloudDocs are refused. `cat` will not open dataless files.

Top 5 missing:

1. Other ubiquity containers (app libraries). Easy to wander into Mail/Messages. Do not.
2. Explicit download. Deferred until Phillip asks; it is a network write.
3. Upload / rename / trash.
4. Share links.
5. Versions. Not on the local placeholder.

### grok-spotlight (new 0.1.0)

Commands: `doctor`, `search`, `gaps`.

Feasibility: `mdfind` needs no new TCC for Documents, Desktop, and Developer. Doctor ran against `/System/Library/CoreServices` only. Search defaults to Documents and Desktop. `--onlyin` is repeatable. Keychains, Messages, Mail, HomeKit, Passes, Safari, and Cookies are refused before `mdfind` runs (Keychains refusal tested).

Security: paths only, limit 50, timeout 15s default. No file bytes.

This is the AFK spike chosen over Safari bookmarks (that plist is privacy-heavy) and Focus status (the Do Not Disturb database is a separate TCC story).

Those two deferrals are done as read-only 0.1.0 spikes: `grok-focus` (best-effort Do Not Disturb database, no write) and `grok-safari` (Bookmarks.plist only). See below.


### grok-focus (new 0.1.0)

Commands: `doctor`, `status`, `set` (`--dry-run`, or `--force` plus `--shortcut`), `gaps`.

Feasibility: `~/Library/DoNotDisturb/DB/Assertions.json` and `ModeConfigurations.json` were readable on this Mac with no new dialog. Doctor on macOS 27.0 saw 5 configured modes and no active assertion (`active: false`). `ModeConfigurationsSecure.json` (per-app allow lists) is not read.

Security: status is best-effort and this Mac only. `set` without `--force` exits `needs_force`. `--dry-run` never runs a shortcut's action (`shortcuts list` only when `--shortcut` is passed). `--force` without `--shortcut` exits `needs_shortcut` and does not write the database. `--force --shortcut NAME` runs that existing shortcut and can do whatever the shortcut does.

Top gaps: no supported Focus API; stale or cross-device status; no silent setter; Sleep and Driving are names only.

### grok-safari (new 0.1.0)

Commands: `doctor`, `bookmarks`, `reading-list`, `search`, `gaps`. All list commands take `--limit` (1–50) and `--json`.

Feasibility: `~/Library/Safari/Bookmarks.plist` was readable (Full Disk Access already effective for this process). Doctor counted 996 bookmarks and 79 Reading List items. History, cookies, passwords, and CloudTabs were not opened.

Security: no writes, no `open` of URLs, no System Settings UI. Output is clipped by `--limit`. Reading List preview text is omitted.

Top gaps: iCloud sync lag; no add/delete; no history search; folder label mapping is only Favorites and Bookmarks Menu.

## Missing surfaces (Mac + iOS 27 continuity)

| Surface | Feasibility | TCC / prompt | Recommendation |
| --- | --- | --- | --- |
| Spotlight | easy | none for user folders | **built** (`grok-spotlight`) |
| Shortcuts as the meta layer | easy | none to list; a run can do anything | **built**, run stays gated |
| Focus | medium | Local Do Not Disturb database, readable here without a new dialog | **built** (`grok-focus` 0.1.0, best-effort, no database write) |
| Notification Center | hard | no honest AppleScript for the stack | defer |
| Safari Reading List / Bookmarks | medium | Bookmarks.plist; FDA already effective here | **built** (`grok-safari` 0.1.0, read-only, no history) |
| Maps | hard | MapKit search is not a local CLI; AppleScript is thin | defer |
| Find My | don't | location of people and devices | never from this desk |
| Screen Time | don't | family controls, no stable CLI | never |
| Continuity Camera | hard | UI / Continuity, not a data API | defer |
| AirDrop | don't | sending files to nearby devices | never as an agent action |
| Freeform | medium | open a board only; layout is not scriptable | defer |
| Journal | don't | almost no AppleScript; store is TCC-walled | never scrape |
| Photos | hard | Photos privacy, huge libraries, destructive edits | defer |
| Voice Memos | don't | explicit prior out | never |
| Weather | easy via a shortcut the user has, or a public API | no local store worth scraping | defer; not Apple-private data |
| Clock / Alarms | medium | Clock has weak scripting; alarms may be Shortcuts | defer |
| System Settings toggles | don't | Wi-Fi, accounts, permissions | never. Tell the user the click |
| App Intents | medium | the `shortcuts` CLI is the supported front door | use grok-shortcuts, do not invent a second runner |
| Widgets / Lock Screen / Control Center / Stage Manager | don't | UI state, not a desk API | never |
| Handoff | don't | no agent API | never |
| Universal Clipboard | medium | `pbpaste` is local but leaks whatever was copied | defer; do not call it unasked |
| iCloud Keychain / Passwords | don't | secrets | **out** |
| Wallet | don't | payments and passes | **out** |
| HomeKit | don't | physical world | **out** |

iOS 27 continuity that is already covered when the Mac is signed into the same iCloud account: Notes, Contacts, Reminders, Calendar, Messages, Shortcuts, iCloud Drive, Mail accounts that Mail.app already has. Find My, Wallet, Journal, and Screen Time do not get a Mac-side scrape to "complete" that continuity.

## Security notes that apply to every CLI

- JSON errors use `ok`, `tool`, `version`, `error`, `code`, `message` on the CLIs touched this pass. `gaps --json` is on every CLI.
- Timeouts stay in the 15–25s band for Apple Events. Spotlight doctor is 15s. No doctor loop.
- Dry-run paths for Calendar create/update/delete, Reminders add, Mail draft, and Shortcuts run do not call the target app (Shortcuts dry-run only runs `shortcuts list`).
- Passwords, Keychain, HomeKit, Wallet, and Find My are not probed.

## Backlog for when Phillip is at the Mac

1. Click Allow for Grok Bot / Grok Bot Helper → Calendar, Reminders, and Mail if those dialogs are still up. Then one `doctor` each. Do not loop.
2. After Calendar doctor is green, `show` one uid and confirm `recurrence`, `attendeeCount`, and `alarmCount` parse.
3. After Reminders doctor is green, `show` one id and confirm `remindMeDate`.
4. After Mail doctor is green, `list` one mailbox and confirm junk/replied. Still no send.
5. Optional later: a Contacts phone index only if Phillip asks, stored 0600, never printed in bulk.
6. Focus and Safari read-only spikes are in. Do not re-run Calendar, Reminders, or Mail doctors until the Automation Allows. Do not enable Focus and do not send Mail or Messages from this work.
