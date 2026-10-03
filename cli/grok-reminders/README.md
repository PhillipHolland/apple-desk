# grok-reminders

Local Apple Reminders CLI. Talks to Reminders.app with `osascript -l JavaScript`. **Not RemCTL**, not EventKit, not a cloud API.

**Status (0.1.1):** Code hardened AFK. Apple Event calls hard-timeout at 20–25s (exit 4 `automation_timeout`). Doctor was blocked on Automation Allow as of 2026-10-03 — do not retry doctor in a loop while AFK. After you click Allow (System Settings → Privacy & Security → Automation → Grok Bot / Grok Bot Helper → Reminders), run `doctor` once.

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
grok-reminders gaps --json
```

`delete` does nothing without `--force` (one `--id` only; no mass delete). Due times are this Mac's local time. JSON auth failures include a `hint`. Exit **3** = denied. Exit **4** = timeout. Never call `remctl`.
