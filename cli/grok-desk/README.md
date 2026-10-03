# grok-desk

Local onboarding for Apple Desk. Version 0.1.4.

Builds search caches on this Mac so later lookups do not walk Notes or `chat.db` from scratch. Nothing is uploaded. No Keychain. No Passwords.

```bash
grok-desk doctor --json
grok-desk onboard --json
grok-desk reindex --json
grok-desk reindex --full --only messages --json
grok-desk reindex --only calendar --json
grok-desk reindex --only calendar --past-days 30 --future-days 90 --json
grok-desk reindex --only reminders --json
grok-desk reindex --only contacts --json   # opt-in; writes phones and emails locally
grok-desk onboard --index-contacts --json  # same opt-in
grok-desk status --json
grok-desk search calendar "standup" --json
grok-desk gaps
```

## Caches

| Surface | Path | When |
| --- | --- | --- |
| Notes | `~/.cache/grok-notes/index.sqlite` | Delegates to `grok-notes reindex`. Not a second database. |
| Messages | `~/.cache/grok-messages/index.sqlite` | Read-only `chat.db`. Chat metadata plus FTS on message text if Full Disk Access allows. `chat.db` is never copied. |
| Contacts | `~/.cache/grok-contacts/index.sqlite` | **Off by default.** Only `onboard --index-contacts` or `reindex --only contacts`. |
| Calendar | `~/.cache/grok-calendar/index.sqlite` | `reindex` runs `grok-calendar doctor` once. If that is ok, stores calendar names plus events from 30 days before today through 90 days after (inclusive). Override with `--past-days` / `--future-days` or `GROK_CALENDAR_PAST_DAYS` / `GROK_CALENDAR_FUTURE_DAYS` (each clamped to 0..366). One calendar index at a time via `grok-calendar list --live` (uid, title, start, end, all-day, calendar name). Only the Apple system calendar titled Scheduled Reminders is skipped by name. A wide window that times out is read in 14-day slices, and each slice is retried once. A slice over 800 events is split further by date. Doctor timeout or denied Automation is `pending_allow` and is not retried. No locations or notes. `grok-desk search calendar` and `grok-calendar list`/`search` read this cache unless `--live`. |
| Reminders | `~/.cache/grok-reminders/index.sqlite` | `reindex` runs `grok-reminders doctor` once. If that is ok, stores list names plus incomplete reminders due today through 60 days (CLI maximum: id, list, title, due). No notes. Timeout or denied Automation is `pending_allow` and is not retried. |

Directories are mode `0700`. Database files are mode `0600`.

Messages may store group chat metadata (guid, display name, counts). That does not change send rules: `grok-messages --to` stays 1:1, and a group send still needs `--chat-guid` after the user names the group.

Onboard's short doctor loop does not call Calendar, Reminders, or Mail, because an Automation dialog can hang. Filling Calendar or Reminders happens in `reindex`, one attempt each. Mail is not indexed.

`grok-focus` and `grok-safari` are reported by `doctor` when they exist. They are not indexed here.

## Signature

Optional one-line footer for the agent. Not appended by any send CLI. Not uploaded.

```bash
grok-desk signature
grok-desk signature --set "- Sent from Ada's Grok Bot"
grok-desk signature --clear
```

File: `~/.config/grok-desk/signature` (mode `0600`). One line, 160 characters max. Ask the user what they want. Do not invent a line. `doctor` reports set or unset and does not print the line.
