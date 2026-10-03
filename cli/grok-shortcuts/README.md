# grok-shortcuts

Thin wrapper around `/usr/bin/shortcuts`.

```bash
grok-shortcuts doctor
grok-shortcuts list
grok-shortcuts list --folders
grok-shortcuts gaps
grok-shortcuts create --name "Note" --comment "Created from the command line." --dry-run
grok-shortcuts create --name "Note" --comment "Created from the command line." --output ~/Desktop/Note.shortcut --force
grok-shortcuts create --name "Note" --comment "Created from the command line." --force
grok-shortcuts run "Shortcut Name" --force
```

`create` does nothing without `--force`. `--dry-run` validates the name and builds the plist in memory; it never signs or opens Shortcuts. `create --force` signs on this Mac with `people-who-know-me` by default (`--sign-mode anyone` is allowed). Signing is local CLI signing, not an iCloud notarization of your library. `--output` writes the signed file and does not open Shortcuts. Without `--output`, Shortcuts.app opens so you can confirm the add. The new shortcut is not run. A generated shortcut is a Comment action, plus Show Result when `--text` is set. `--from file.shortcut` signs a file you already have. This does not edit or delete shortcuts, and it does not build an arbitrary action graph.

`run` does nothing without `--force`. A shortcut can message, call, control Home, or write files. This wrapper does not inspect the shortcut, so it will not guess which ones are safe. Do not pass `--force` unless the user named that shortcut.

`list` and `doctor` never run a shortcut. `grok-shortcuts gaps` is the limit list.
