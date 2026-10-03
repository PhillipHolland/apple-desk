# grok-focus

Best-effort Focus / Do Not Disturb status for any Mac. Discovers modes from
`~/Library/DoNotDisturb/DB` on this Mac. Does not open System Settings and does
not write the Focus database.

```bash
grok-focus doctor
grok-focus status --json
grok-focus modes
grok-focus set --mode "Do Not Disturb" --dry-run
grok-focus set --mode "Do Not Disturb" --shortcut "Name" --force   # runs that shortcut only
grok-focus cache-clear
grok-focus gaps --json
```

`set` without `--force` refuses. `--dry-run` never changes Focus, even with
`--force`. There is no built-in toggle: `--force` still requires `--shortcut` of
a shortcut you already have.

Optional cache: `~/.cache/grok-focus` (mode catalog only, invalidated by
`ModeConfigurations.json` mtime).

Status can be wrong if this Mac's assertion file is stale or Focus is on only on
another device. Mode names are discovered per Mac; nothing is hardcoded to one
host.
