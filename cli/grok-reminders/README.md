# grok-reminders

Local Apple Reminders CLI. Talks to Reminders.app with `osascript -l JavaScript`. Not RemCTL, not EventKit, not a cloud API.

```bash
grok-reminders doctor
grok-reminders lists
grok-reminders today
grok-reminders upcoming --days 7
grok-reminders search "query"
grok-reminders show --id REMINDERID
grok-reminders add --title "Call office" --list "Reminders" --due "2026-10-04 09:00" --priority high
grok-reminders done --id REMINDERID
grok-reminders delete --id REMINDERID --force
grok-reminders gaps
```

`delete` does nothing without `--force`. Due times are this Mac's local time. If doctor exits 3 or 4, a Reminders Automation grant is missing or a dialog is up. Stop. Do not loop.

`grok-reminders gaps` lists what this cannot do (smart lists, subtasks, recurrence, sharing, and the rest).
