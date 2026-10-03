# grok-shortcuts

Thin wrapper around `/usr/bin/shortcuts`.

```bash
grok-shortcuts doctor
grok-shortcuts list
grok-shortcuts list --folders
grok-shortcuts gaps
grok-shortcuts run "Shortcut Name" --force
```

`run` does nothing without `--force`. A shortcut can message, call, control Home, or write files. This wrapper does not inspect the shortcut, so it will not guess which ones are safe. Do not pass `--force` unless the user named that shortcut.

`list` and `doctor` never run a shortcut. `grok-shortcuts gaps` is the limit list.
