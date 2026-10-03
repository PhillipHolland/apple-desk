# grok-mail

Apple Mail CLI for this Mac. It talks to Mail.app with `osascript -l JavaScript` (JXA). It does not read `~/Library/Mail` and it does not call a cloud mail API.

Reads are the default. `draft` saves one unsent message only when you pass `--force`. Version 0.1.0 has no `send` command. The script never calls Mail's send command.

```bash
grok-mail doctor
grok-mail accounts
grok-mail mailboxes
grok-mail list --mailbox INBOX --limit 3
grok-mail show --id MSGID
grok-mail search "invoice" --mailbox INBOX --limit 5
grok-mail gaps

grok-mail draft --to person@example.com --subject "Hello" --body "Not sent yet"
grok-mail draft --to person@example.com --subject "Hello" --body "Not sent yet" --force
```

Add `--json` on any command. `list` and `search` print subject, date, and sender only. `show` adds a body clipped to 1200 characters. `--limit` is 1..50 (default 20).

`draft` without `--force` exits `needs_force` and does not call Mail. Nothing is created. With `--force`, Mail gets one hidden outgoing message (`visible: false`) and `save`. That is a draft, not a send. Do not use `--force` unless a person asked for that exact draft.

The first Mail command needs Automation permission for the calling app to control Mail (System Settings → Privacy & Security → Automation → Grok Bot, Grok Bot Helper, Terminal, or osascript → Mail). Error -1743 exits 3 (`automation_denied`). A hung permission dialog or error -1712 exits 4 (`automation_timeout`). One attempt, then stop. Do not retry in a loop while a dialog is up. This CLI will not click the dialog.

`draft --force` can still fail after reads work, because composing is a separate Mail access group (`com.apple.mail.compose`).
