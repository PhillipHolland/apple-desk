# grok-safari

Read Safari bookmarks and Reading List from `~/Library/Safari/Bookmarks.plist`. Does not modify bookmarks or open URLs.

```bash
grok-safari doctor
grok-safari bookmarks --json --limit 20
grok-safari reading-list --json --limit 20
grok-safari search "query" --json --limit 20
grok-safari gaps --json
```

If the plist is not readable, `doctor` exits `needs_full_disk_access` and does not open System Settings. History, cookies, and passwords are out of scope.
