# grok-safari

Read Safari bookmarks and Reading List from `~/Library/Safari/Bookmarks.plist`
on any Mac. Does not modify bookmarks or open URLs.

```bash
grok-safari doctor
grok-safari status --json
grok-safari bookmarks --json --limit 20
grok-safari reading-list --json --limit 20
grok-safari search "query" --json --limit 20
grok-safari reindex
grok-safari cache-clear
grok-safari gaps --json
```

Doctor is a lean count-only walk. `bookmarks`, `reading-list`, and `search` hit
`~/.cache/grok-safari` first when the plist mtime matches; otherwise they
rebuild the cache.

If the plist is not readable, `doctor` exits `needs_full_disk_access` and does
not open System Settings. History, cookies, and passwords are out of scope.
