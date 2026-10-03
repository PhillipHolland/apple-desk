# grok-calendar

Apple Calendar CLI for this Mac. Talks to Calendar.app with `osascript -l JavaScript` (JXA). Not EventKit, not Google Calendar, not iCloud.com.

**Status (0.1.1):** Code hardened AFK. Apple Event calls hard-timeout at 20–25s (exit 4 `automation_timeout`). Doctor was blocked on Automation Allow as of 2026-10-03 — do not retry doctor in a loop while AFK. After you click Allow (System Settings → Privacy & Security → Automation → Grok Bot / Grok Bot Helper → Calendar), run `doctor` once.

Reads are the default. `create` and `update` are explicit mutations. `delete` removes one event and needs `--uid` plus `--force`. There is no mass delete. `create --dry-run` validates args without calling Calendar.app.

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
```

Add `--json` on any command. JSON auth failures include a `hint` with the exact System Settings path. Exit **3** = `automation_denied` / `calendar_tcc`. Exit **4** = timeout (dialog may be waiting). One attempt, then stop.
