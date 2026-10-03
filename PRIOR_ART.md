# Prior art (credited, not copied)

Apple Desk studies public agent-facing Mac CLIs and keeps its own codepaths.
This file names patterns we learn from. It is not a license to vendor their trees.

## openclaw/imsg

- Repo: https://github.com/openclaw/imsg
- Patterns absorbed: read `chat.db` in SQLite read-only mode; NDJSON/JSON for agents; Full Disk Access for history; Automation only for send; separate read vs send surfaces; chat id / GUID selectors; no private IMCore / SIP tricks.
- Apple Desk mapping: `grok-messages` history/search/unread stay on chat.db; `send` stays gated (`--force` / allowlist) and `--to` is 1:1 only.
- Refused: copying imsg source, its watch/RPC stack, or any IMCore private API approach.

## danielhopkins/apple-tools (MIT)

- Repo: https://github.com/danielhopkins/apple-tools
- Patterns absorbed: one `status` across tools; permission probes that do not prompt; local-only CLIs; Calendar/Contacts/Reminders as first-class agent tools; honest TCC states (including Calendar “Add Only”).
- Apple Desk mapping: `grok-desk status` is the unified rollup (caches + doctor probes); each `grok-* doctor` stays lean and portable under `~/.cache/grok-*`.
- Refused: vendoring apple-tools binaries or Swift sources into this private repo.

## omarshahine/apple-pim (EventKit)

- Repo: https://github.com/omarshahine/apple-pim
- Patterns absorbed: EventKit for Calendar/Reminders instead of full AppleScript/JXA walks; lean doctor/status; batch reads; domain isolation.
- Apple Desk today: `grok-calendar` and `grok-reminders` still use JXA against Calendar.app / Reminders.app with count-only doctors and bounded reindex windows. EventKit remains the preferred next backend when those CLIs are free of concurrent edits.
- Refused: copying apple-pim Swift CLIs or MCP plugin code.

## Explicit non-goals / refusals

- Do **not** copy RemCTL or NotesCTL.
- Do **not** use Viticci product names as Apple Desk command names.
- Do **not** disable SIP or call private IMCore.
- Do **not** ship Passwords, HomeKit, or Keychain tooling here.
- Credit upstream in docs; keep Apple Desk command names (`grok-*`) stable.
