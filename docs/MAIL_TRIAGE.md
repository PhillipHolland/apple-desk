# Mail triage

`grok-mail` in this build is read-only plus draft. It can inspect mail and create a draft. It does not send.

## Commands in this build

These subcommands exist:

- `doctor`
- `accounts`
- `mailboxes`
- `list`
- `show`
- `search`
- `draft`
- `gaps`

`flag`, `move`, and `mark-read` are not subcommands in this build.

There is no `send` command. There is no SMTP path.

## Contract when mutating commands exist

When `flag`, `move`, and `mark-read` exist, they follow this contract:

- The default is a dry-run. A dry-run does not call Mail.app.
- `--force` is the only apply path.
- These commands never send mail. There is no SMTP client and no `send` subcommand.

A command without `--force` reports the planned change and leaves the mailbox unchanged. The same command with `--force` is the only form that applies the change.

## Placeholders

Examples use placeholders only. Do not put host names, email addresses, phone numbers, subjects, or personal account names in this doc or in sample output.

```text
grok-mail doctor
grok-mail accounts
grok-mail mailboxes <account>
grok-mail list <account> <mailbox>
grok-mail show <account> <message-id>
grok-mail search <account> <query>
grok-mail draft <account> <recipient> <subject> <body>
grok-mail gaps

# not subcommands in this build; contract when they exist
grok-mail flag <account> <message-id> <flag>
grok-mail flag --force <account> <message-id> <flag>
grok-mail move <account> <message-id> <mailbox>
grok-mail move --force <account> <message-id> <mailbox>
grok-mail mark-read <account> <message-id>
grok-mail mark-read --force <account> <message-id>
```
