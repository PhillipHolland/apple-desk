# grok-calendar

Apple Calendar CLI for this Mac. It talks to Calendar.app with `osascript -l JavaScript` (JXA). It does not use EventKit directly and it does not call Google Calendar or iCloud.com.

Reads are the default. `create` and `update` are explicit mutations. `delete` removes one event and needs `--uid` plus `--force`. There is no mass delete.

```bash
grok-calendar doctor
grok-calendar calendars
grok-calendar list
grok-calendar list --today
grok-calendar list --from 2026-10-03 --to 2026-10-10 --calendar "Calendar"
grok-calendar search "standup" --days 14
grok-calendar show --uid EVENTUID
grok-calendar gaps

grok-calendar create --calendar "Calendar" --title "Dentist" --start "2026-10-08 15:00" --end "2026-10-08 16:00"
grok-calendar update --uid EVENTUID --location "Office"
grok-calendar delete --uid EVENTUID --force
```

Add `--json` on any command. `list` prints titles and times only. `show` adds location, notes, url, and recurrence text for one event.

The first Calendar command needs Automation permission for the calling app to control Calendar (System Settings → Privacy & Security → Automation → Grok Bot and Grok Bot Helper → Calendar). Error -1743 means that grant is missing. If a dialog says “Grok Bot” wants access to control “Calendar”, click Allow once. If events still fail, also enable Grok Bot and Grok Bot Helper under Privacy & Security → Calendars, then quit and reopen Grok Bot. Do not retry in a loop while a dialog is up.
