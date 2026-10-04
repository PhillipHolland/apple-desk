# Focus and Safari

Worked recipes for `grok-focus` and `grok-safari` on any Mac. Mode names are whatever `grok-focus modes` prints where it runs. Bookmark titles stay on that Mac. The Messages draft that uses `grok-focus status` is `docs/FOCUS_ETIQUETTE.md`. That recipe does not call `grok-focus set`.

## grok-focus

`grok-focus` reads `~/Library/DoNotDisturb/DB`: configured modes from `ModeConfigurations.json`, active assertions from `Assertions.json`. `doctor`, `status`, and `modes` are read-only. They do not open System Settings. The Do Not Disturb database is never written.

Optional cache: `~/.cache/grok-focus`, a mode catalog invalidated by `ModeConfigurations.json` mtime.

```bash
grok-focus doctor
grok-focus status
grok-focus status --json
grok-focus status --json --lean
grok-focus modes
grok-focus cache-clear
grok-focus gaps
```

`status` prints `Focus on: …` or `Focus off on this Mac (best-effort)`, then the configured modes it discovered. `--lean` keeps names and identifiers and omits symbol fields. `modes` prints each name and identifier. `cache-clear` removes the mode catalog only.

`doctor` reports whether the database directory is present, how many modes it discovered, and whether an assertion is active on this Mac. A missing store is a fresh-Mac hint, not a write: turn on any Focus once from Control Center so `DoNotDisturb/DB` exists. If the files exist and are unreadable, grant Full Disk Access to the process running the CLI. `grok-focus` does not open System Settings.

Status is best-effort. No assertion list is treated as Focus off on this Mac. The file can lag, and another signed-in device can be in a different Focus.

### set

`set` refuses without `--force`. With `--force` it only runs an existing Shortcut name. `--mode` is a name or identifier from `modes` on that Mac. `--dry-run` never changes Focus, including when `--force` is also present.

```bash
grok-focus set --mode "<mode>" --shortcut "<shortcut>"
grok-focus set --mode "<mode>" --shortcut "<shortcut>" --dry-run
grok-focus set --mode "<mode>" --force
grok-focus set --mode "<mode>" --shortcut "<shortcut>" --force
```

Without `--force`, the command exits `needs_force` and prints `Refusing to enable or change Focus without --force. Nothing was changed.`

The dry-run prints `dry-run: would not change Focus` and the mode name. When `--shortcut` is present it also prints whether that name is installed. It does not run the shortcut.

`--force` without `--shortcut` exits `needs_shortcut`. There is no built-in setter. The Do Not Disturb database is never written.

`--force` with `--shortcut` runs that shortcut only when `shortcuts list` already contains the name. An unknown name exits `unknown_shortcut` and runs nothing. A shortcut that ran can do whatever that shortcut does. Confirm with `grok-focus status`. `grok-focus` did not write the Do Not Disturb database.

## grok-safari

`grok-safari` reads bookmarks and Reading List from `~/Library/Safari/Bookmarks.plist`. History, passwords, cookies, and URL opens are out. Bookmarks and Reading List rows are not added, edited, or deleted. Nothing is written back to Safari.

Optional cache: `~/.cache/grok-safari`, a SQLite index invalidated by the plist mtime. `bookmarks`, `reading-list`, and `search` use it when the mtime matches.

`doctor` is a count-only walk, so a large bookmark file stays lean. If the plist is missing or unreadable, `doctor` exits `needs_full_disk_access` and does not open System Settings. On a fresh Mac, open Safari once so `~/Library/Safari/Bookmarks.plist` exists. If the file exists and is unreadable, grant Full Disk Access to the process running the CLI.

```bash
grok-safari doctor
grok-safari status
grok-safari status --json
grok-safari bookmarks --limit 20
grok-safari reading-list --limit 20
grok-safari search "query" --limit 20
grok-safari reindex
grok-safari cache-clear
grok-safari gaps
```

`--limit` is 1 through 50. The default is 20. `search` needs at least 2 characters. `bookmarks` prints folder, title, and URL. `reading-list` prints title and URL. `search` prints `bookmark` or `reading-list`, then title and URL. `reindex` rebuilds the cache. `cache-clear` removes the index only.

### to-note

`to-note` prepares one Note from one Reading List item through `grok-notes create-note`. Dry-run is the default. `--force` is the only apply path. The same contract is in `docs/SAFARI_READING_LIST_NOTE.md`.

Pass one of `--index`, `--url`, or `--title`. `--index` is 1-based and follows `reading-list` order. `--url` and `--title` must match one item exactly. When two items share that URL or title, pass `--index`.

```bash
grok-safari to-note --index 1
grok-safari to-note --url "https://example.invalid/article"
grok-safari to-note --title "Exact title" --folder "Reading"
grok-safari to-note --index 1 --force
```

The dry-run prints `dry-run: would create one note`, the title, and the URL. Reading List was only read. Notes.app was not called. The URL was not opened.

After an explicit yes, the same selection with `--force` creates one note. The note title is the item title. The note body is the URL. Optional `--folder` is passed through to `grok-notes create-note`. Reading List is unchanged, and the URL is not opened.

## Counts stay out of this doc

Timings, bookmark counts, and Reading List counts measured on one Mac belong in the agent report for that run. This doc keeps the commands and the gates above.
