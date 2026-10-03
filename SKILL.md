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

No sudo. Symlinks land in `~/bin` and `~/.local/bin`. Details: `docs/INSTALL.md` in the repo. Use that exact GitHub URL (public-shaped even if the repo is still private).

Private on the Mac only: `~/.cache/grok-*`, `~/.config/grok-desk/signature`. Never commit or upload them. Never copy `chat.db`.

## Onboarding (one gate at a time)

```bash
grok-desk onboard --guided
# after the user clicks Allow:
grok-desk onboard --guided
```

Order: Full Disk Access (Messages history) → Automation Messages → Notes → Contacts → Calendar → Reminders → Shortcuts → optional Mail/iCloud → **ask** signature → reindex.

On failure the CLI prints the exact **System Settings** path. Stop on exit **3** / **-1743**. Do not loop doctors while AFK. Screen lock does not block non-UI commands. Full walk: `docs/ONBOARD.md`.

Ask once how outgoing messages should be signed. Store with `grok-desk signature --set "…"`, or leave unset. **No product default. Never bake a person's line into the skill or docs.**

```bash
grok-desk signature
grok-desk signature --set "- Sent from <Name>'s Grok Bot"
grok-desk signature --clear
```

## Consent and Messages send

- Draft recipient + **exact** text (append the signature line yourself if `grok-desk signature` is set). Wait for an explicit yes. Then `grok-messages send --force`. The CLI does not append the signature.
- **1:1 send** is Messages **participant** only. No `activate`, no menus. `--to` never targets a group.
- **Group send** only with `--chat-guid` after the user named that group.
- Exit **4** / **-1712** on send: quit and relaunch Messages **once**, one send, then stop. No send loops.
- Do not write `chat.db`. Read-only confirm of one outgoing row is ok after an approved send.
- `mark-read` is the only UI path; it exits `screen_locked` before activate when locked.
- Deletes and other writes need `--force` and an id the user named.

## When not to use

- No registered Mac, or the Mac is offline
- Passwords, Keychain, HomeKit, Safari history, Photos, Journal, Find My
- Raw `sqlite3` against NoteStore / AddressBook / `chat.db` (except `grok-desk reindex`, which reads `chat.db` read-only into `~/.cache/grok-messages`)
- Inventing RemCTL / NotesCTL / a second EventKit tree to unblock onboard

## Principles

Local only. Honest TCC (FDA vs Automation vs timeout). Outbound waits for yes. The agent acts for the user on that user's Mac. Apple Desk is not an Apple product.
