---
name: Apple Desk
description: >-
  Use when the user wants Apple Reminders, Calendar, Notes, Contacts,
  iMessage, Shortcuts, Mail.app, iCloud Drive, Spotlight paths, Focus,
  Safari bookmarks, or first-run Mac onboarding for those tools.
  Thin skill: install the repo, consent/send rules, guided onboard.
  Not Google Calendar, not Passwords, not HomeKit, not cloud Apple APIs.
---
# Apple Desk

Mac-local Apple CLIs for the agent. Not a cloud connector. Run every command on the user's registered Mac (`machineId`). Never on the cloud box. Never on a phone.

This skill stays **thin**. It does not embed the codebase. Install the repo, then use the CLIs' own `--help` / `gaps`.

## Install (pull the repo)

```bash
mkdir -p ~/Developer && cd ~/Developer
git clone https://github.com/PhillipHolland/apple-desk.git apple-desk
# or: git -C apple-desk pull --ff-only
cd ~/Developer/apple-desk
./scripts/onboard.sh
```

No sudo. Symlinks land in `~/bin` and `~/.local/bin`. Details: `docs/INSTALL.md` in the repo. Clone URL is the public repo: https://github.com/PhillipHolland/apple-desk.

Private on the Mac only: `~/.cache/grok-*`, `~/.config/grok-desk/signature`. Never commit or upload them. Never copy `chat.db`.

## Onboarding (one gate at a time)

```bash
grok-desk onboard --guided
# after the user clicks Allow:
grok-desk onboard --guided
```

Order: Full Disk Access (Messages history) → Automation Messages → Notes → Contacts → Calendar → Reminders → Shortcuts → optional Mail/iCloud → **ask** signature → reindex.

On failure the CLI prints the exact **System Settings** path. Use the recovery card below. Do not loop doctors while AFK. Full walk: `docs/ONBOARD.md`.

Ask once how outgoing messages should be signed. Store with `grok-desk signature --set "…"`, or leave unset. **No product default. Never bake a person's line into the skill or docs.**

```bash
grok-desk signature
grok-desk signature --set "- Sent from <Name>'s Grok Bot"
grok-desk signature --clear
```

## First win (after the minimum gate only)

- `grok-messages unread` (Full Disk Access + Messages automation)
- `grok-notes search` (Notes automation)
- `grok-reminders today` (Reminders automation)

## Notes markdown

`grok-notes import-md FILE` and `grok-notes export-md --out FILE` talk to Notes.app. Both are a dry-run unless `--force`. Import will not edit an existing title. Limits (heading depth, quotes, footnotes, images, drawings) are in `cli/grok-notes/README.md`.

PARA folders and hashtags (`#project/x`, `#area/y`, `#waiting`, `#ref`) are recipes in `docs/NOTES_PARA.md`. Use `create-folder`, `create-note`, and `tags`. No extra app and no extra database.

Snooze a Messages chat by creating a Reminder whose notes contain the chat guid. Recipe: `docs/MESSAGES_SNOOZE.md`.

Before an outbound send or react, include `grok-focus status` in the draft. Recipe: `docs/FOCUS_ETIQUETTE.md`.

## Morning briefing

Read-only unread counts, today's reminders, and the calendar: `docs/MORNING_BRIEFING.md`.

## Recovery

| Signal | Action |
| --- | --- |
| 3, -1743 | Stop and open the Settings path. No loop. |
| 4 | Stop for one Allow click. |
| 5 | Full Disk Access. |
| -1712 | Quit and relaunch Messages once, then one send, then stop. |
| screen_locked | mark-read only. Unlock, then one retry. Never loop. |

## Consent and Messages send

- Draft recipient + **exact** text (append the signature line yourself if `grok-desk signature` is set). Wait for an explicit yes. Then `grok-messages send --force`. The CLI does not append the signature.
- Before an outbound send or react, the draft confirmation must include the output of `grok-focus status`. Focus filters the sender's UI more than the recipient's notifications. Do not block the send. Do not refuse `--force` because Focus is on. Do not activate Messages. Do not call `grok-focus set`.
- **1:1 send** is Messages **participant** only. No `activate`, no menus. `--to` never targets a group.
- **Group send** only with `--chat-guid` after the user named that group.
- Send failures use the recovery card: **4** stops for one Allow click; **-1712** quits and relaunches Messages once, then one send, then stop.
- Do not write `chat.db`. Read-only confirm of one outgoing row is ok after an approved send.
- `mark-read` exits `screen_locked` before activate when locked. `react --force` does not pre-check the lock and does not activate Messages. Vendor `imsg react` activates Messages itself and exits -2700 if Messages is not in front, so a locked screen still cannot finish a tapback. imsg tapback is not a fallback: it needs SIP disabled and imsg launch, which Apple Desk will not do.
- Deletes and other writes need `--force` and an id the user named.

## Tapbacks v1 (shipped)

`grok-messages react` is shipped. It stays 1:1 only, and it is a dry-run unless `--force`. Dry-run prints the chat rowid, a short last non-reaction snippet, the reaction, and the exact command `imsg react --chat-id <rowid> --reaction <love|like|dislike|laugh|emphasis|question>`. `--force` does not pre-check the screen lock and does not activate Messages. It runs that command once. Vendor imsg react activates Messages itself and exits -2700 if Messages is not in front. Wrap the `imsg` binary that implements `react` (`$GROK_MESSAGES_IMSG` when executable, else the source checkout `~/Developer/vendor/imsg` release binary). Do not brew-install. Do not copy AppleScript. Do not call `imsg tapback`, `imsg launch`, or IMCore. `imsg react` hits the last-or-selected message, not a GUID. Groups are refused. No `chat.db` writes. A missing binary is `missing_imsg` on `--force`, not an AppleScript fallback. Our wrap does not exit `screen_locked`. Vendor imsg still fails -2700 when Messages is not in front. The only non-UI tapback in that binary is imsg tapback, which injects IMCore and refuses to run while SIP is enabled. Apple Desk does not disable SIP, does not run imsg launch, and does not call imsg tapback. Locked-screen tapbacks are parked.

## When not to use

- No registered Mac, or the Mac is offline
- Passwords, Keychain, HomeKit, Safari history, Photos, Journal, Find My
- Raw `sqlite3` against NoteStore / AddressBook / `chat.db` (except `grok-desk reindex`, which reads `chat.db` read-only into `~/.cache/grok-messages`)
- Inventing RemCTL / NotesCTL / a second EventKit tree to unblock onboard

## Principles

Local only. Honest TCC (FDA vs Automation vs timeout). Outbound waits for yes. The agent acts for the user on that user's Mac. Apple Desk is not an Apple product.
