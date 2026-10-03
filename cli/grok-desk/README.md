# grok-desk

Local onboarding for Apple Desk. Version 0.1.0.

Builds search caches on this Mac so later lookups do not walk Notes or `chat.db` from scratch. Nothing is uploaded. No Keychain. No Passwords.

```bash
grok-desk doctor --json
grok-desk onboard --json
grok-desk reindex --json
grok-desk reindex --full --only messages --json
grok-desk reindex --only contacts --json   # opt-in; writes phones and emails locally
grok-desk onboard --index-contacts --json  # same opt-in
grok-desk status --json
grok-desk gaps
```

## Caches

| Surface | Path | When |
| --- | --- | --- |
| Notes | `~/.cache/grok-notes/index.sqlite` | Delegates to `grok-notes reindex`. Not a second database. |
| Messages | `~/.cache/grok-messages/index.sqlite` | Read-only `chat.db`. Chat metadata plus FTS on message text if Full Disk Access allows. `chat.db` is never copied. |
| Contacts | `~/.cache/grok-contacts/index.sqlite` | **Off by default.** Only `onboard --index-contacts` or `reindex --only contacts`. |
| Calendar | `~/.cache/grok-calendar/index.sqlite` | Empty schema, `pending_allow`. This version does not call Calendar. |
| Reminders | `~/.cache/grok-reminders/index.sqlite` | Empty schema, `pending_allow`. This version does not call Reminders. |

Directories are mode `0700`. Database files are mode `0600`.

Messages may store group chat metadata (guid, display name, counts). That does not change send rules: `grok-messages --to` stays 1:1, and a group send still needs `--chat-guid` after the user names the group.

Calendar, Reminders, and Mail are version-checked only during onboard. Their doctors are not run, because an Automation Allow dialog can hang.

`grok-focus` and `grok-safari` are reported by `doctor` when they exist. They are not indexed here.
