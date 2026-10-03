# grok-notes

Apple Notes CLI for this Mac. It talks to Notes.app with `osascript -l JavaScript` (JXA). Search uses a local SQLite cache so it does not walk every note through Apple Events.

It does **not** read `NoteStore.sqlite`. This is an interim stand-in until [MacStories NotesCTL](https://github.com/viticci/notesctl) is public open source. It is not the Club MacStories NotesCTL beta and not the unrelated `jwmoss/notesctl` exporter. The command is named `grok-notes` so it does not occupy `notesctl`.

```bash
grok-notes doctor
grok-notes reindex            # incremental; first run reads every body
grok-notes reindex --full
grok-notes search "query"     # cache, usually milliseconds
grok-notes search "query" --live
grok-notes folders
grok-notes folders --cached
grok-notes list Notes --limit 20
grok-notes show "Exact Title" --folder Notes
grok-notes show --id NOTEID
grok-notes tags
grok-notes gaps

grok-notes create-note --title "Title" --body "text" --folder "Notes"
grok-notes create-folder "Name" --parent "Parent"
grok-notes edit --id NOTEID --append "more text"
grok-notes edit --id NOTEID --rename "New title"
grok-notes move --id NOTEID --to-folder "Notes"
grok-notes duplicate --id NOTEID   # Notes 4.13 refuses: can not be copied
grok-notes delete-note --id NOTEID --force
grok-notes delete-note --id NOTEID --force --permanent
grok-notes delete-folder "Name" --force
grok-notes empty-trash --force
grok-notes checklist show --id NOTEID
grok-notes checklist add --id NOTEID --text "item"
grok-notes attachments --id NOTEID
grok-notes share --id NOTEID
grok-notes cache-clear
```

Add `--json` for JSON. Deletes need `--force`. Deleting a folder named Notes, a folder with subfolders, or a folder with more than 30 notes also needs `--allow-large`.

`reindex` writes plaintext (capped at 200000 characters per note) to `~/.cache/grok-notes/index.sqlite` (directory `0700`, file `0600`). That file is not iCloud. `cache-clear` removes the index only. After creates, edits, moves, or deletes, run `reindex` before expecting `search` to see them. `search` does not take `--live` unless you want the old slow Apple Event walk.

`pin`, `unpin`, `lock`, and `unlock` exit with an error. They are not scriptable. `grok-notes gaps` lists the rest (share sheet, checked checklists, drawings, scans, attachment bytes, smart folders).

The first successful Notes command needs Automation permission for the calling app to control Notes (System Settings → Privacy & Security → Automation). Error -1743 means that grant is missing.
