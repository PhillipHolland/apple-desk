# Combined Mail and Calendar implementation (0.2.0)

Apple Desk originally exposed lightweight Mail scripting and a Calendar path split between optional external tools, app scripting, and a cache. This change keeps the existing app commands and provides a common `apple-desk` entry point, an owned EventKit backend, and a bounded Mail backend.

## Behavior changes

- Mail search no longer enumerates the entire mailbox or requests its total count before returning a page. Filters are evaluated before full metadata where possible; search stops at the match limit, scan limit, or cooperative page budget. True stalls preserve completed candidates and a resumable cursor.
- Mail references identify the account, mailbox, local message ID and RFC Message-ID. Triage verifies the selected message and resulting state. Archive and trash require an explicit destination rather than guessing account-specific special folders.
- Local drafts support review and compose handoff. Sends and event creation use a private, durable journal. An uncertain operation cannot be re-executed under the same key. A completed operation replays its result.
- Calendar uses one native EventKit helper with full-access permission setup, real event identifiers, occurrence context, strict dates/time zones, free-time calculation, and independent local readback after writes. A local success does not prove remote synchronization.
- Ordinary diagnostics and onboarding are passive. Explicit indexing records window, coverage, freshness, and incomplete refreshes; it cannot silently become the live Calendar source.
- The optional Reminders backend no longer drops `--dry-run` before executing a mutation.

## Compatibility

The `grok-*` launchers remain. Mail and Calendar now emit the shared JSON envelope; integrations must read results from `data`. Legacy Mail draft flags return migration guidance to durable JSON drafts. Numeric Mail IDs need account/mailbox context, and old synthetic Calendar IDs must be rediscovered. Calendar reads use EventKit directly. Existing caches are not a substitute for full access.

No personal caches, live account identifiers, drafts, attachments, credentials, or generated binaries belong in the contribution. Other app tools retain their original limits. No MCP server is added.

## Validation boundary

The regression suite uses synthetic mailboxes, native pure-logic tests, fake subprocesses, temporary SQLite caches, and temporary state stores. It checks cursor/limit/budget behavior, true timeout recovery, write uncertainty, idempotency, date/DST validation, verification logic, and stale/incomplete index handling. It does not send real messages or mutate the real calendar store. Permission and provider-specific behavior still needs opt-in live validation on a development Mac.
