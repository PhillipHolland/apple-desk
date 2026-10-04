# Morning briefing

A read-only pass over unread messages, today's reminders, and the calendar. Use the existing CLIs. There is no extra app. Do not mark messages read. Do not create or delete events. Do not create or delete reminders.

```bash
grok-messages unread
grok-reminders today
grok-calendar list --today
grok-calendar list --from YYYY-MM-DD --days 2 --limit 3
```

`unread` prints counts. It does not mark a chat read.

`grok-reminders today` lists reminders. It does not create or complete one.

`grok-calendar list --today` is today. `--from` is `YYYY-MM-DD` or `YYYY-MM-DD HH:MM`. Put today's date there. `--days` is the window length when `--to` is omitted (default 7), so `--days 2` is a two-day window. `--limit 3` keeps that second list to three events. Leave off `--live`. The default list reads the local index and does not create or delete events.
