# Notes PARA and tags

A folder and hashtag recipe for Apple Notes. It uses `grok-notes` only. There is no extra app and no extra database.

Tags are words in the note text, not tag objects. `grok-notes tags` counts them from the local search cache after `reindex`. A tag matches `(start or whitespace) #` plus a letter, then letters, digits, `_`, `/`, or `-`, up to 64 characters. `#project/example` counts. Smart folders are not scriptable.

## Four folders

| Folder | What belongs there |
| --- | --- |
| Projects | Outcomes with a finish line |
| Areas | Ongoing responsibilities with no finish line |
| Resources | Reference material you might use later |
| Archives | Inactive projects, areas, and resources |

## Tags

| Tag | Use |
| --- | --- |
| `#project/name` | One active project |
| `#area/name` | One ongoing area |
| `#waiting` | Blocked on someone or something else |
| `#ref` | Reference material |

Put the tag in the note body, after a space or at the start of a line.

## Scaffold

`create-folder` and `create-note` write immediately. There is no dry-run. If a folder already exists, the command exits and leaves it in place. New folders land in the default Notes account.

```bash
grok-notes create-folder "Projects"
grok-notes create-folder "Areas"
grok-notes create-folder "Resources"
grok-notes create-folder "Archives"

grok-notes create-note --folder "Projects" --title "Projects hub" --body "$(cat <<'EOF'
Active outcomes with a finish line.

#project/example

Now
- Name the outcome and when it is done.

#waiting
EOF
)"

grok-notes create-note --folder "Areas" --title "Areas hub" --body "$(cat <<'EOF'
Ongoing responsibilities.

#area/example
EOF
)"

grok-notes create-note --folder "Resources" --title "Resources hub" --body "$(cat <<'EOF'
Reference material.

#ref
EOF
)"

grok-notes create-note --folder "Archives" --title "Archives hub" --body "$(cat <<'EOF'
Inactive items live here. Move a note here when a project ends.
EOF
)"

grok-notes reindex
grok-notes tags
grok-notes tags --folder Projects
grok-notes list Projects --limit 20
grok-notes search waiting
```

`search` matches the word `waiting`. The `#` is not part of the search token. Use `tags` to count hashtags.

`create-note --body` stores plain paragraphs, not Markdown headings. For a Markdown hub, `import-md` is a dry-run unless `--force`, and it will not change a note that already has that title:

```bash
grok-notes import-md ./projects-hub.md --title "Projects hub" --folder Projects
grok-notes import-md ./projects-hub.md --title "Projects hub" --folder Projects --force
```

Move a finished project note into Archives:

```bash
grok-notes move --id NOTEID --to-folder "Archives"
```

Run `reindex` again after creates or moves before `tags` or `search`. Markdown limits for `import-md` and `export-md` are in `cli/grok-notes/README.md`.
