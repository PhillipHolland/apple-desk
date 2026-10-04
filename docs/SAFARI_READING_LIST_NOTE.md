# Reading List item to one Note

`grok-safari to-note` prepares one Note from one Safari Reading List item. Dry-run is the default. `--force` is the only apply path.

The dry-run reads the Reading List and does not call Notes. It does not create a note. `--force` calls the existing `grok-notes create-note` path (Notes.app JavaScript for Automation). This is not a second Notes backend. Reading List items are not added, edited, deleted, or opened. URLs are not launched.

## Command

```bash
grok-safari to-note --index 1
grok-safari to-note --url "https://example.invalid/article"
grok-safari to-note --title "Exact Reading List title"
grok-safari to-note --index 1 --folder "Reading"
grok-safari to-note --index 1 --force
```

`--index` is 1-based and matches the order from `grok-safari reading-list`. `--url` and `--title` must match one item exactly. If two items share that title or URL, pass `--index`. Pass only one of `--index`, `--url`, or `--title`.

The note title is that item title. The note body is the item URL as plain text, through `grok-notes create-note --title ... --body ...`. Optional `--folder` is passed through only when `create-note` already accepts a folder.

## What this does not do

Safari bookmarks and Reading List stay unchanged. `to-note` does not open the URL, does not call `open`, and does not add or remove Reading List rows. History, passwords, and cookies stay out of scope.
