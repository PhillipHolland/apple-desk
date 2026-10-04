# grok-mail

Apple Mail CLI for this Mac. Talks to Mail.app with `osascript -l JavaScript` (JXA). It does not read `~/Library/Mail` and it does not call a cloud mail API.

**Prefer the Gmail connector** for cloud mail. Use `grok-mail` only when you need Mail.app on this Mac.

**Status (0.1.1):** Code hardened AFK. Apple Event calls hard-timeout at 20–25s (exit 4 `automation_timeout`). Doctor timed out 2026-10-03 — do not retry doctor in a loop while AFK. After you click Allow (System Settings → Privacy & Security → Automation → Grok Bot / Grok Bot Helper → Mail), run `doctor` once.

Reads are the default. `draft` saves one unsent message only with `--force`. There is **no `send` command**. The script never calls Mail's send.

```bash
grok-mail doctor
grok-mail accounts
grok-mail mailboxes
grok-mail list --mailbox INBOX --limit 3
grok-mail show --id MSGID
grok-mail search "invoice" --mailbox INBOX --limit 5
grok-mail gaps

grok-mail draft --to person@example.com --subject "Hello" --body "Not sent yet"
grok-mail draft --to person@example.com --subject "Hello" --body "Not sent yet" --dry-run
grok-mail draft --to person@example.com --subject "Hello" --body "Not sent yet" --force
```

Add `--json` on any command. `list` / `search` print subject, date, and sender only. `show` body is clipped to **800** characters. `draft --body` is capped at **4000** characters. `--limit` is 1..50 (default 20).

`draft` without `--force` exits `needs_force` and does not call Mail. `--dry-run` also skips Mail. With `--force`, Mail gets one hidden outgoing message and `save`. That is a draft, not a send.

Exit **3** = `automation_denied`. Exit **4** = `automation_timeout` (dialog may be waiting). JSON includes a `hint`. One attempt, then stop. This CLI will not click the dialog.
