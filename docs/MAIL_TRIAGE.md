# Mail triage

`grok-mail` can inspect mail, save a draft, and change flag, mailbox, and read state. It does not send.

## Commands in this build

These subcommands exist:

- `doctor`
- `accounts`
- `mailboxes`
- `list`
- `show`
- `search`
- `draft`
- `flag`
- `move`
- `mark-read`
- `gaps`

There is no `send` command. There is no SMTP path.

## Mutating commands

`flag`, `move`, and `mark-read` follow this contract:

- The default is a dry-run. A dry-run does not call Mail.app.
- `--force` is the only apply path.
- These commands never send mail. There is no SMTP client and no `send` subcommand.

A command without `--force` reports the planned change and leaves the mailbox unchanged. The same command with `--force` is the only form that applies the change.

`flag --state flagged` or `flag --state unflagged` sets flagged status. `mark-read` sets read status. `move --to` moves one message into that mailbox.

## Placeholders

Examples use placeholders only. Do not put host names, email addresses, phone numbers, subjects, or personal account names in this doc or in sample output.

```text
grok-mail doctor
grok-mail accounts
grok-mail mailboxes --account <account>
grok-mail list --account <account> --mailbox <mailbox>
grok-mail show --account <account> --id <message-id>
grok-mail search --account <account> <query>
grok-mail draft --to <recipient> --subject <subject> --body <body>
grok-mail gaps

grok-mail flag --id <message-id> --state flagged --mailbox <mailbox> --account <account>
grok-mail flag --id <message-id> --state unflagged --force
grok-mail move --id <message-id> --to <mailbox> --mailbox <mailbox> --account <account>
grok-mail move --id <message-id> --to <mailbox> --force
grok-mail mark-read --id <message-id> --mailbox <mailbox> --account <account>
grok-mail mark-read --id <message-id> --force
```
