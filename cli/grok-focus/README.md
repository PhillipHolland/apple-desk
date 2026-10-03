# grok-focus

Best-effort Focus / Do Not Disturb status for macOS 27. Reads the local Do Not Disturb database. Does not open System Settings.

```bash
grok-focus doctor
grok-focus status --json
grok-focus set --mode "Do Not Disturb" --dry-run
grok-focus set --mode "Do Not Disturb" --shortcut "Name" --force   # runs that shortcut only
grok-focus gaps --json
```

`set` without `--force` refuses. `--dry-run` never changes Focus, even with `--force`. There is no built-in toggle: `--force` still requires `--shortcut` of a shortcut you already have, and the database is never written.

Status can be wrong if this Mac's assertion file is stale or Focus is on only on another device.
