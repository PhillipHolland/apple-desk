# Notes Smart Folders

Smart Folders are a Notes feature. They are not scriptable on this JavaScript for Automation path. Do not add a `smart-folder` command. `grok-notes gaps` already lists smart folders with the other things this CLI cannot do.

A person creates a Smart Folder in Notes. They can also run a Shortcut they already have. This repo does not ship a new Shortcut file.

Until that folder exists, the PARA tags in [NOTES_PARA.md](NOTES_PARA.md) can stand in for one. A tag is text in the note, not a folder object. `grok-notes tags` counts those hashtags from the local cache after `reindex`.

## What grok-notes can do instead

These are ordinary folders and note text, not Smart Folders:

```bash
grok-notes folders
grok-notes folders --cached
grok-notes create-folder "Projects"
grok-notes list Projects --limit 20
grok-notes move --id NOTEID --to-folder "Projects"
grok-notes tags
grok-notes tags --folder Projects
grok-notes search waiting
grok-notes reindex
```

`create-folder` writes immediately. There is no dry-run. If the folder already exists, the command exits and leaves it in place. `search` matches words. The `#` is not part of the search token. Use `tags` to count hashtags such as `#project/name`, `#area/name`, `#waiting`, and `#ref`.

Markdown import and export are a dry-run unless `--force`. Import will not edit a note that already has that exact title. Export writes `--out` only with `--force`, and it will not overwrite that file unless `--replace`.

```bash
grok-notes import-md ./note.md --folder Notes
grok-notes import-md ./note.md --folder Notes --force
grok-notes export-md "Exact Title" --folder Notes --out ./note.md
grok-notes export-md --id NOTEID --out ./note.md --force
```

After `import-md --force`, or after a create or move, run `reindex` before you expect `search` or `tags` to see the change. Markdown limits are in `cli/grok-notes/README.md`. The folder and hashtag recipe is in [NOTES_PARA.md](NOTES_PARA.md).
