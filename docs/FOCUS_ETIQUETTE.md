# Focus etiquette

Before an outbound Messages draft (send or react), show `grok-focus status` in the same confirmation as the recipient and the exact text. Wait for an explicit yes.

Focus filters the sender's UI more than the recipient's notifications.

If a Sleep or Work mode is on, prefer capturing a Reminder or a Note, and leave the send decision to the human. Do not block the send. Do not refuse `--force` because Focus is on. Do not activate Messages. Do not call `grok-focus set`.

`grok-focus status`, `doctor`, and `modes` are read-only. This Messages recipe calls `grok-focus status` and does not call `grok-focus set`. The rest of the Focus and Safari commands are in `docs/FOCUS_AND_SAFARI.md`.

## Status in the draft

```bash
grok-focus status
```

Paste that output beside the recipient and the exact text. The first line is `Focus on: …` or `Focus off on this Mac (best-effort)`. The following lines are the configured-mode count, one line per configured mode, and `assertions mtime:` when the assertion file has a time. Status is best-effort and this Mac only. Another signed-in device can be in a different Focus, and the file can lag.

```text
To: <recipient>
Text: <exact text>
Focus:
<paste grok-focus status>
```

For a send, the exact text is the full string passed to `--text`. For a react, the recipient is the `--to` person, the exact text is the dry-run snippet, and the draft also names the reaction.

## React draft

`react` is a dry-run unless `--force`. The dry-run prints the chat rowid, the reaction, a short snippet, and the vendor command. It applies nothing.

```bash
grok-messages react --to "<recipient>" --reaction love
```

Reactions are `love`, `like`, `dislike`, `laugh`, `emphasis`, and `question`. `emphasize` means `emphasis`. `react` has no `--text` and no `--chat-guid`. Put the printed snippet in the draft as the exact text, with the recipient, the reaction, and the `grok-focus status` output.

## Sleep or Work

When an active mode is named Sleep or Work, offer a Reminder or a Note in the same draft, and still ask whether to send or react.

`grok-reminders add` writes unless `--dry-run`. It has no `--force`. Show the dry-run first.

```bash
grok-reminders add --title "Send later" --notes "$(cat <<'EOF'
To: <recipient>
Text: <exact text>
EOF
)" --dry-run
```

That prints `dry-run add 'Send later' (Reminders not called)`. After an explicit yes for the reminder, run the same command without `--dry-run`.

`grok-notes create-note` writes immediately. It has no dry-run. Run it only after an explicit yes for the note.

```bash
grok-notes create-note --title "Send later" --body "$(cat <<'EOF'
To: <recipient>
Text: <exact text>
EOF
)"
```

A yes for the Reminder or the Note captures that item. A yes for the send or the react is a separate answer. Neither capture sends a message or applies a reaction.

## Send or react after yes

After an explicit yes, run the existing command with `--force`. Focus being on still gets `--force`.

A 1:1 send uses `--to` for a person.

```bash
grok-messages send --to "<recipient>" --text "<exact text>" --force
```

`send` with neither `--force` nor `--dry-run` refuses, and nothing is sent. `--dry-run` resolves the route and still sends nothing, including when `--force` is also present. The apply command is `--force` without `--dry-run`.

A group send uses `--chat-guid` after the user named that group. Pass `--to` or `--chat-guid`, one of them.

```bash
grok-messages send --chat-guid "<chat-guid>" --text "<exact text>" --force
```

A react after yes:

```bash
grok-messages react --to "<recipient>" --reaction love --force
```

`send --force` does not activate Messages. `react --force` does not activate Messages before it runs the existing vendor command. The outbound command is one of those two.
