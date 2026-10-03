# grok-icloud

Finder-class view of the local iCloud Drive folder:

`~/Library/Mobile Documents/com~apple~CloudDocs`

```bash
grok-icloud doctor
grok-icloud doctor --json
grok-icloud ls
grok-icloud ls "Some Folder" --limit 50 --json
grok-icloud tree --depth 2
grok-icloud find "*.txt" --limit 20 --json
grok-icloud cat "notes/todo.txt" --max-bytes 8192
grok-icloud gaps
```

Evicted files (dataless, or names ending in `.icloud`) are reported as `evicted` and are not opened. This CLI does not download them. There is no `--download` in 0.1.0.

`cat` prints only a file that is already local and within `--max-bytes` (default 8192, hard cap 65536). UTF-8 is preferred. Older Mac text and RTF that fail UTF-8 but pass a binary sniff are decoded as Latin-1. Known binary suffixes are refused before the file is read. Oversized files are refused with no body.

`doctor` says whether macOS Desktop & Documents sync is on by checking that `~/Desktop` or `~/Documents` is the same directory as the copy inside iCloud Drive. A folder that is merely named Desktop inside Drive is not the Mac Desktop.

`grok-icloud gaps` is the limit list. Paths outside CloudDocs are refused. No Mail, Messages, or Keychain.
