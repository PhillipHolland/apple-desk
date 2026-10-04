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
grok-notes promote-checklist --id NOTEID --index 1
grok-notes promote-checklist --id NOTEID --text "Pack bag" --due "2026-10-04"
grok-notes promote-checklist --id NOTEID --index 1 --force
grok-notes attachments --id NOTEID
grok-notes share --id NOTEID
grok-notes cache-clear

grok-notes import-md ./note.md --folder Notes
grok-notes import-md ./note.md --folder Notes --force
grok-notes export-md "Exact Title" --folder Notes --out ./note.md
grok-notes export-md --id NOTEID --out ./note.md --force
```

Add `--json` for JSON. Deletes need `--force`. Deleting a folder named Notes, a folder with subfolders, or a folder with more than 30 notes also needs `--allow-large`.

`reindex` writes plaintext (capped at 200000 characters per note) to `~/.cache/grok-notes/index.sqlite` (directory `0700`, file `0600`). That file is not iCloud. `cache-clear` removes the index only. After creates, edits, moves, or deletes, run `reindex` before expecting `search` to see them. `search` does not take `--live` unless you want the old slow Apple Event walk.

`pin`, `unpin`, `lock`, and `unlock` exit with an error. They are not scriptable. `grok-notes gaps` lists the rest (share sheet, checked checklists, drawings, scans, attachment bytes, smart folders).


## Checklist to one reminder

`promote-checklist` turns one checklist line into one reminder. It is a dry-run unless `--force`. The dry-run reads that note (`show`) and does not call Reminders.app. `--force` adds one reminder through `grok-reminders add` (Reminders.app JXA). It does not use a second reminders backend.

Pass `--id` and either `--index` (1-based, same order as `checklist show`) or `--text` (one exact line). `--due` is optional (`YYYY-MM-DD` or `YYYY-MM-DD HH:MM`). Omit it and the reminder has no due date. `--list` chooses the Reminders list; omit it and add uses the default list.

The reminder title is the checklist line. The reminder notes are a plain-text backlink with the note title and the note id. The checklist line is not marked done. Notes rewrote `checked`, `done`, and `class` off `<li>` on write, so checked-state is not reliable. The link-a-note UI is not scriptable, so the backlink stays text on the reminder. See [docs/NOTES_CHECKLIST_REMINDER.md](../../docs/NOTES_CHECKLIST_REMINDER.md).

## Markdown import and export

`import-md` and `export-md` are a dry-run unless `--force`. Import reads a UTF-8 file and does not call Notes until `--force`. It will not edit a note that already has that exact title. Export reads one note. It writes `--out` only with `--force`, and it will not overwrite that file unless `--replace`.

Notes can import and export Markdown from **File > Import Markdown** and **File > Export To > Markdown**. Those items are not in the Notes 4.13 scripting dictionary, so this CLI does not drive the file dialogs. It converts a Markdown subset to the HTML Notes keeps, using the same JXA create and show path as `create-note` and `show`.

`tests/markdown-roundtrip-sample.md` is the disposable sample. Importing it creates a note titled `Apple Desk markdown round-trip sample`. On Notes 4.13 that round-trip kept:

- Three heading sizes, bullet lists, and numbered lists
- Bold, italic, strikethrough, and links
- Simple pipe-table cell text
- One nested item, stored as a sibling list and indented again on export
- Task markers `[ ]` and `[x]` as list text
- Fenced code as monospaced lines
- Footnote markers as literal text

Notes did not preserve:

- A fourth heading size (`####` comes back as a subheading)
- Block quotes (the `>` is dropped and the words stay a paragraph)
- Real checklists (task markers are not Notes checkboxes)
- Nested-list formatting inside the parent item
- Table alignment, merged cells, and captions (Notes plaintext shows a placeholder for the table; `export-md` reads the HTML cells)
- Footnotes as notes
- Markdown images as attachments (the address comes back as a link)
- A code-fence language
- Drawings, handwriting, scans, and named attachment bytes

After `import-md --force`, run `reindex` before you expect `search` or `tags` to see the new note.

Folder and hashtag recipes (Projects, Areas, Resources, Archives, `#project/name`, `#area/name`, `#waiting`, `#ref`) are in [docs/NOTES_PARA.md](../../docs/NOTES_PARA.md).

Smart Folders are not scriptable. Coaching, and the commands that stand in for one, are in [docs/NOTES_SMART_FOLDERS.md](../../docs/NOTES_SMART_FOLDERS.md).

The first successful Notes command needs Automation permission for the calling app to control Notes (System Settings → Privacy & Security → Automation). Error -1743 means that grant is missing.
