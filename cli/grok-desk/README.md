# grok-desk

Local setup checks and explicit search indexing for Apple Desk 0.2.0. Available as
`apple-desk desk` or the retained `grok-desk` command. Data stays on this Mac.

```bash
apple-desk desk doctor --json
apple-desk desk onboard --guided --json
apple-desk desk status --json
apple-desk permissions request --mail
apple-desk permissions request --calendar
apple-desk desk reindex --only calendar --past-days 30 --future-days 90 --json
apple-desk desk search calendar "standup" --json
apple-desk desk reindex --only contacts --json
apple-desk desk reindex --full --only messages --json
apple-desk desk gaps --json
```

`onboard`, including `--guided`, is passive: it reports installed versions, local
cache state, and bounded Mail/Calendar authorization diagnostics. It does not ask
macOS for permissions, create links, or build indexes. Other app tools receive
version checks only. A successful doctor process does not mean access is granted:
Mail must report `allowed: true`, and Calendar must report `fullAccess: true` with
authorization `fullAccess`. The output provides explicit permission commands when
needed. Legacy onboarding flags `--full`, `--index-contacts`, and
`--skip-signature` remain accepted but do not start indexing or require a signature.

Run `reindex` deliberately to build caches. Legacy Notes, Messages, Contacts, and
Reminders indexers retain their original access requirements and limitations;
their explicit indexing commands may require macOS access. Mail is not indexed.

## Calendar cache

`reindex --only calendar` uses the owned EventKit backend after a passive full
access check. It stores schema 4 at `~/.cache/grok-calendar/index.sqlite`, with
real calendar IDs, event IDs, occurrence references, exact start and end values,
all-day types, and time zones. Duplicate calendar names stay distinct. Notes,
locations, URLs, attendees, and alarms are omitted from this search index.

The default window includes 30 days before today through 90 days after today.
Override with `--past-days` and `--future-days`, or
`GROK_CALENDAR_PAST_DAYS` and `GROK_CALENDAR_FUTURE_DAYS`; each is clamped to
0..366. Reads use explicit timestamps in windows of at most 31 days, at most 800
events per page, and at most 100 pages per calendar/window. Each backend call has
a deadline. Timeouts are recorded without automatic retries.

An incomplete or invalid page makes the index explicitly partial. Permission or
backend failure before collection preserves an existing snapshot, marks it stale,
and leaves its successful indexing timestamp unchanged. Snapshots also become
stale after 24 hours. Old schemas require an explicit reindex. Empty, authorized,
fully read windows are valid complete snapshots.

Calendar cache searches report their coverage, freshness, and completeness. They
return a failure status for stale or partial caches while retaining available
matches. Optional bounds must both be ISO timestamps with UTC offsets, fall
entirely inside the cached window, and use an exclusive upper bound. Matching
uses actual overlapping instants, including all-day time zones and DST.

```bash
apple-desk desk search calendar "standup" --from 2026-10-03T00:00:00Z --to 2026-10-04T00:00:00Z --calendar-id CALENDAR_ID --limit 20 --json
```

Only `grok-desk search calendar` uses this cache. `apple-desk calendar list` and
`search` always read EventKit directly. Cache completeness describes the collected
window, not remote synchronization or another person's availability.

## Other local caches

| Surface | Path | Contents and trigger |
| --- | --- | --- |
| Notes | `~/.cache/grok-notes/index.sqlite` | Explicit reindex delegates to `grok-notes reindex`; no second database. |
| Messages | `~/.cache/grok-messages/index.sqlite` | Explicit reindex reads `chat.db` without copying it, subject to Full Disk Access; includes chat metadata and message text search. |
| Contacts | `~/.cache/grok-contacts/index.sqlite` | Opt in with `reindex --only contacts` or `reindex --index-contacts`; stores phones and email addresses locally. |
| Reminders | `~/.cache/grok-reminders/index.sqlite` | Explicit reindex collects incomplete reminders due today through 60 days with original backend limits; no notes. |

Directories use mode `0700`; database files use mode `0600`. Messages may include
group chat metadata. Sending still requires the user's concrete authorization;
the existence of a cache is not permission to send.

## Signature

The optional one-line footer is stored locally and never appended automatically
by a send CLI. `doctor` reports whether it is set without printing it.

```bash
grok-desk signature
grok-desk signature --set "- Sent from my assistant"
grok-desk signature --clear
```

File: `~/.config/grok-desk/signature`, mode `0600`, at most 160 characters on one
line. Ask the user for the desired text; do not invent it.
