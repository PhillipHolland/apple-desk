# grok-calendar

Apple Calendar CLI for this Mac. Talks to Calendar.app with `osascript -l JavaScript` (JXA). Not EventKit, not Google Calendar, not iCloud.com.

**Status (0.1.6):** Doctor is count-only (Calendar.app version and calendar count). It does not walk names or events. `name-at --index` reads one name. `list` and `search` use `~/.cache/grok-calendar` when that index is `ok`; pass `--live` to read Calendar.app for one `--index` or `--calendar`. The desk reindex window (past 30 days, next 90 days) is documented on `grok-desk`, not hard-coded to one Mac. Do not retry `doctor` in a loop while an Automation prompt may be up.

Reads are the default. `create` and `update` are explicit mutations. `delete` removes one event and needs `--uid` plus `--force`. `alarm` adds one display alarm and stays a dry-run unless `--force`. A dry-run does not call Calendar.app. There is no mass delete. Events cannot move between calendars; see `docs/CALENDAR_LIMITS.md`.

`show` returns an attendee count only. Attendee and RSVP names are omitted unless you explicitly ask, and this CLI has no command that prints them.

```bash
grok-calendar doctor
grok-calendar calendars
grok-calendar list
grok-calendar list --today
grok-calendar list --from 2026-10-03 --to 2026-10-10 --calendar "Calendar"
grok-calendar search "standup" --days 14
grok-calendar show --uid EVENTUID
grok-calendar gaps

grok-calendar create --calendar "Calendar" --title "Dentist" --start "2026-10-08 15:00" --end "2026-10-08 16:00" --dry-run
grok-calendar create --calendar "Calendar" --title "Dentist" --start "2026-10-08 15:00" --end "2026-10-08 16:00"
grok-calendar update --uid EVENTUID --location "Office"
grok-calendar delete --uid EVENTUID --force
grok-calendar alarm --uid EVENTUID --minutes 15
grok-calendar alarm --uid EVENTUID --minutes 15 --force
```

Add `--json` on any command. JSON auth failures include a `hint` with the exact System Settings path. Exit **3** = `automation_denied` / `calendar_tcc`. Exit **4** = timeout (dialog may be waiting). One attempt, then stop.
