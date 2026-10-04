# grok-safari

Read Safari bookmarks and Reading List from `~/Library/Safari/Bookmarks.plist`
on any Mac. Does not modify bookmarks or open URLs. `to-note` can create one
Note from a Reading List item through `grok-notes create-note`; dry-run is the
default.

```bash
grok-safari doctor
grok-safari status --json
grok-safari bookmarks --json --limit 20
grok-safari reading-list --json --limit 20
grok-safari search "query" --json --limit 20
grok-safari to-note --index 1
grok-safari to-note --url "https://example.invalid/article"
grok-safari to-note --title "Exact title" --folder "Reading"
grok-safari to-note --index 1 --force
grok-safari reindex
grok-safari cache-clear
grok-safari gaps --json
```

Doctor is a lean count-only walk. `bookmarks`, `reading-list`, and `search` hit
`~/.cache/grok-safari` first when the plist mtime matches; otherwise they
rebuild the cache.

`to-note` selects one Reading List item by `--index`, exact `--url`, or exact
`--title`. Without `--force` it prints the title and URL and does not call
Notes. With `--force` it creates one note through `grok-notes create-note`
(title = item title, body = URL). Optional `--folder` is passed through.

If the plist is not readable, `doctor` exits `needs_full_disk_access` and does
not open System Settings. History, cookies, and passwords are out of scope.
