# Coverage

The combined 0.2.0 build keeps existing Apple Desk tools and adds the `apple-desk` dispatcher. The authoritative syntax is each installed command's `--help`; declarations here are implementation coverage, not evidence that this Mac has granted permission or that every account provider has been live-tested.

| Surface | Implementation |
| --- | --- |
| Mail | Fixed JXA request protocol; accounts/mailboxes, bounded search and cursor resume, read, attachment list/save, verified mark/flag/move/archive/trash, local drafts, compose handoff, explicit idempotent send |
| Calendar | One native EventKit helper; calendars, bounded-window event queries, read/search, free time, create/update/delete, recurrence scopes, strict date validation and local write readback |
| Desk | Passive diagnostics/onboarding; explicit Notes/Messages/Contacts/Calendar/Reminders indexes; status, search and optional signature |
| Reminders | Existing scripting/optional external backend; external dry-run mutation handling corrected |
| Notes, Contacts, Messages, Shortcuts, iCloud, Spotlight, Focus, Safari | Existing command coverage retained; see tool README/help and GAPS.md |

Calendar has no external-PIM or scripting fallback and does not silently use a local cache. Mail does not access the private Mail database. Optional desk caches cannot establish that a live read would be complete. State directories and caches are private and excluded from source control.

## Agent execution contract

Mail and Calendar use the shared JSON envelope, including `data` on partial failures. Search limits bound matches and scanning; cooperative page budgets can return a short successful page with a cursor. Hard stalls remain errors with resumable completed work where possible.

An agent must obtain authorization for the concrete write. Sends and event creation use a durable idempotency key; an uncertain operation cannot be blindly retried. Local drafts are separate from native compose windows. Mail acceptance does not confirm delivery. Messages keeps its existing recipient and group restrictions. No write to chat.db, SIP change, or IMCore injection is part of this tool.

## Tapbacks v1 (shipped)

`grok-messages react` is shipped. It stays 1:1 only, and it is a dry-run unless `--force`.

Dry-run prints the chat rowid, a short last non-reaction snippet, the reaction, and the exact command `imsg react --chat-id <rowid> --reaction <love|like|dislike|laugh|emphasis|question>`. `--force` does not pre-check the screen lock and does not activate Messages. It runs that command once. Vendor imsg react activates Messages itself and exits -2700 if Messages is not in front.

Wrap the `imsg` binary that implements `react` (`$GROK_MESSAGES_IMSG` when executable, else the source checkout `~/Developer/vendor/imsg` release binary). Do not brew-install. Do not copy AppleScript. Do not call `imsg tapback`, `imsg launch`, or IMCore. `imsg react` hits the last-or-selected message, not a GUID. Groups are refused. No `chat.db` writes. A missing binary is `missing_imsg` on `--force`, not an AppleScript fallback. Our wrap does not exit `screen_locked`. Vendor imsg still fails -2700 when Messages is not in front. The only non-UI tapback in that binary is imsg tapback, which injects IMCore and refuses to run while SIP is enabled. Apple Desk does not disable SIP, does not run imsg launch, and does not call imsg tapback. Locked-screen tapbacks are parked.


## Validation and remaining gaps

Offline regressions cover Mail search/filter/cursor/timeout behavior, private state and idempotency, Calendar date/DST/reference/verification logic, and complete/partial/stale index behavior. These checks do not mutate real Mail or Calendar data. Permission/provider-specific behavior needs opt-in live validation.

No MCP server, Mail HTML composer, permanent Mail deletion, delivery tracking, Calendar RSVP/attendee editor, password/Keychain tool, HomeKit, Photos, or general System Settings controller is implemented. Other proposed peer integrations remain future choices for the maintainer; they are not dependencies of the new Mail and Calendar backends.
