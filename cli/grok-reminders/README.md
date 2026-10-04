# grok-reminders

Local Apple Reminders CLI. Talks to Reminders.app with `osascript -l JavaScript`. **Not RemCTL**, not EventKit, not a cloud API.

**Status (0.1.5):** Code hardened AFK. Apple Event calls hard-timeout at 20–25s (exit 4 `automation_timeout`). Doctor was blocked on Automation Allow as of 2026-10-03 — do not retry doctor in a loop while AFK. After you click Allow (System Settings → Privacy & Security → Automation → Grok Bot / Grok Bot Helper → Reminders), run `doctor` once.

```bash
grok-reminders doctor
grok-reminders lists
grok-reminders today
grok-reminders upcoming --days 7
grok-reminders search "query"
grok-reminders show --id REMINDERID
grok-reminders add --title "Call office" --list "Reminders" --due "2026-10-04 09:00" --priority high
grok-reminders done --id REMINDERID
grok-reminders flag --id REMINDERID --state flagged
grok-reminders flag --id REMINDERID --state unflagged --force
grok-reminders move --id REMINDERID --to "Example"
grok-reminders move --id REMINDERID --to "Example" --force
grok-reminders delete --id REMINDERID --force
grok-reminders gaps --json
```

`flag` and `move` default to a dry-run and do **not** call Reminders.app. Pass `--force` to apply. Do not `--force` against real reminders unless the user asked. `delete` also refuses without `--force` (one `--id` only; no mass delete). Due times are this Mac's local time. JSON auth failures include a `hint`. Exit **3** = denied. Exit **4** = timeout. Never call `remctl`.

## Recurrence

Recurrence is **not** available on this JXA path. There is no recurrence write or series edit here, and EventKit is not in this build. Use Reminders.app itself (or a future approved wrap) for repeating reminders. See `grok-reminders gaps`.

## Sections and smart lists

Sections and smart lists are not scriptable on this JXA path. See `docs/REMINDERS_SECTIONS.md`. Create them in Reminders.app, or run a Shortcut you already have. This CLI can `lists`, `add`, `done`, `move`, and `flag`. `move` and `flag` stay dry-run unless `--force`. Recurrence is still not available. There is no `section` or `smart-list` command.
