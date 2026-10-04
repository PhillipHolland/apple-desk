# grok-calendar

Apple Desk's local Calendar CLI uses its own native EventKit helper on macOS 14+. It reads the calendars already configured on your Mac. The Python facade always returns the shared versioned JSON envelope; `--json` remains accepted for agent compatibility. `apple-desk calendar` forwards to the same implementation.

There is one backend: `native/dist/apple-desk-calendar`. The old JXA script, external `calendar-cli` wrapper, and implicit calendar-cache reader have been removed. Reads return actual EventKit identifiers, complete start/end fields, calendar identity and occurrence references. No command falls back to another implementation. The separate desk index is an explicitly refreshed local snapshot.

## Install and access

Build from the repository root with `bash native/build.sh`; the combined installer ships that signed helper unchanged. Swift 6 and Apple's Command Line Tools or Xcode are required to build.

```sh
grok-calendar doctor --json
grok-calendar auth-status --json
grok-calendar permissions request --json
grok-calendar calendars --json
```

Doctor and auth-status do not prompt, launch Calendar, or inspect events. Only `permissions request` asks macOS for full calendar access. Denial is reported as `PERMISSION_REQUIRED`. Grant attribution depends on the calling app and helper identity; ad-hoc signed binary updates can require renewed grants. Keep the installed path stable.

## Read and find time

```sh
grok-calendar list --today --json
grok-calendar list --calendar-id CALENDAR_ID --from 2026-10-03 --to 2026-10-10 --time-zone America/New_York --limit 100 --offset 0 --json
grok-calendar search standup --days 14 --json
grok-calendar show --uid EVENT_REFERENCE --json
grok-calendar read EVENT_REFERENCE --json
grok-calendar free --from 2026-10-05T09:00:00-04:00 --to 2026-10-05T17:00:00-04:00 --duration 30m --json
```

`--calendar-id` is the preferred selector. `--calendar` resolves an exact unique title and rejects duplicate names. `calendars` includes actual IDs, source names and writable status. Legacy `name-at --index` and read-only list/search `--index` are accepted, but indices are not stable references.

Date-only query `--to` is inclusive for compatibility; explicit timestamp `--to` is exclusive. Query windows are bounded to 366 days, with limits 1–1000 and offset pagination. Events include `total`, `count`, `offset`, `limit` and `truncated`. `--light` omits notes, location, alarms, attendees and recurrence details. `--live` is accepted; all direct reads already use EventKit. Free time treats busy, tentative, unavailable and unknown availability as blocking; canceled and explicitly free events do not block. It does not infer working hours or other people's private availability.

Event rows contain `id` and compatibility `uid`, plus an opaque `reference` starting `event:`. Use the reference for edits: it retains calendar identity, item identity, occurrence context and the observed start. IDs may change after synchronization or moves; stale references require a fresh query. All-day dates have exclusive end dates and an explicit system `timeZone` field. Timed starts/ends are instants with UTC offsets.

## Validate and write

```sh
grok-calendar create --calendar-id CALENDAR_ID --title Focus --start '2026-10-05 09:00' --time-zone America/New_York --dry-run --json
grok-calendar create --input event.json --idempotency-key focus-2026-10-05 --json
grok-calendar update --uid EVENT_REFERENCE --location Office --json
grok-calendar delete --uid EVENT_REFERENCE --force --json
```

Timed local input requires `--time-zone` or JSON `timeZone`; offset-bearing ISO timestamps need no additional zone. Ambiguous repeated times require an explicit offset, and nonexistent DST times are rejected. A missing create end becomes one hour after a timed start or the next calendar date for an all-day event. Use an IANA zone on timed recurring events to preserve wall-clock scheduling across DST.

An input file supports:

```json
{
  "calendarId": "CALENDAR_ID",
  "title": "Focus",
  "start": "2026-10-05T09:00:00-04:00",
  "end": "2026-10-05T10:00:00-04:00",
  "timeZone": "America/New_York",
  "availability": "busy",
  "alarms": [{"minutesBefore": 10}],
  "recurrence": {"frequency": "weekly", "interval": 1, "count": 4}
}
```

Optional fields are `allDay`, `notes`, `location`, `url`, `availability`, `alarms`, and `recurrence`. Notes/location/url accept null to clear. Alarms accept `minutesBefore` or an absolute `at` timestamp; `[]` removes alarms. Recurrence accepts daily/weekly/monthly/yearly frequency, positive interval, either count or until, and optional weekdays 1–7 (Sunday=1, not with daily). `recurrence:null` removes the rule. Advanced recurrence rules can be read but are not all expressible as new input. `--alarms` and `--recurrence` accept equivalent JSON values inline.

For all-day events use `allDay:true` and date-only start/end. End is exclusive. EventKit treats these as floating dates in the system calendar zone: supplied `timeZone` is normalized away and does not shift dates. Changing all-day mode on update requires both start and end. Attendees are read-only; invitations and RSVP writes are unsupported.

Recurring updates and deletes require explicit `--scope this` or `--scope future`. An encoded reference supplies the occurrence; a raw ID also needs `--occurrence` with an offset timestamp. `future` means this occurrence and those following, not every occurrence in the series. Calendar or occurrence options that conflict with an encoded reference are rejected.

`--dry-run` is fully offline. It validates structure, dates, recurrence and reference context without starting the helper or requesting permissions. It reports `calendarVerified:false` and `targetVerified:false`: existence, actual recurrence state, permission and writability are checked only during live operations. It never claims a write occurred.

Creation requires an idempotency key. Successful repeated keys replay their original result; changed payloads conflict; uncertain earlier writes are never repeated automatically. Update/delete are serialized locally and never automatically retried. After a write, native readback verifies requested fields; `VERIFICATION_FAILED` and `WRITE_STATUS_UNKNOWN` indicate that a write may already have taken effect. Verification does not prove remote account synchronization. Inspect current state before retrying.

## Native protocol and tests

The helper accepts a JSON object on stdin, or `--request FILE`, and returns `{ok,data,error}`. The Python CLI adds the shared `{schemaVersion,ok,data,error,meta}` envelope. Requests contain `action`, optional `options`, `input`, and `target`. Calendar actions are doctor/auth-status, permissions, calendars, events, free, read, validate-create, create, update, and delete. The same helper offers no-prompt Mail permission status and an explicit Mail permission request; it does not read mail bodies.

```sh
bash native/test.sh
python3 -m unittest discover -s tests -p 'test_calendar*.py'
```

Unit tests and offline CLI tests do not request permissions, read personal events or create live fixtures. Provider-specific recurrence and write behavior still require explicitly authorized on-device integration tests.
