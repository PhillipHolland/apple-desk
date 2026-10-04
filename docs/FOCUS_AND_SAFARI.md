# Focus and Safari CLIs (portable)

Product notes for `grok-focus` and `grok-safari`. These tools are meant for any
user on any Mac in the Apple Desk ecosystem. Build-host checks are verification
only, not product behavior.

## grok-focus

- Reads `~/Library/DoNotDisturb/DB` (discovered modes + assertions).
- `doctor` / `status` / `modes` are read-only.
- `set` refuses without `--force`, and even then only runs an existing Shortcuts
  name. The Do Not Disturb database is never written.
- Optional cache: `~/.cache/grok-focus` (mode catalog).
- No hardcoding of machine names, account names, or one host's Focus mode list.

## grok-safari

- Bookmarks and Reading List from `~/Library/Safari/Bookmarks.plist`.
- No history, passwords, cookies, Reading List edits, or URL opens.
- `to-note` creates one Note from one Reading List item through `grok-notes create-note`. Dry-run is the default; `--force` is the only apply path. The note title is the item title and the body is the URL.
- Optional cache: `~/.cache/grok-safari` (SQLite), invalidated by plist mtime.
- Doctor uses a count-only walk so large bookmark files stay lean.

## Fresh Mac onboard hints

1. Focus: turn on any Focus once from Control Center so `DoNotDisturb/DB` exists.
2. Safari: open Safari once so `~/Library/Safari/Bookmarks.plist` exists.
3. If either file exists but is unreadable, grant Full Disk Access to the process
   running the CLI. Neither tool opens System Settings for you.

## Host verification (not product)

Timings and row counts measured on a particular build Mac belong in the agent
report, not in product defaults, mode lists, or bookmark titles.
