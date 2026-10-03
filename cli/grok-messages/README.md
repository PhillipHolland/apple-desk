# grok-messages

Local Apple Messages CLI for this Mac. Sending goes through Messages.app (`osascript -l JavaScript`). History is read from `~/Library/Messages/chat.db` (Full Disk Access). It does not use a cloud iMessage API.

```bash
grok-messages doctor
grok-messages unread --limit 20
grok-messages mark-read --all --force
grok-messages chats --limit 30
grok-messages chats --query "Ada"
grok-messages recent --to "+15551212" --limit 15
grok-messages search "query" --limit 15
grok-messages gaps

grok-messages send --to "+15551212" --text "hello" --dry-run
grok-messages send --to "+15551212" --text "hello" --force
grok-messages send --chat-guid "iMessage;+;chat..." --text "hello" --dry-run
```

Add `--json` on any command except `gaps`. `unread` counts incoming rows with `is_read = 0`. It does not return message text, does not mark anything read, and does not call Messages.app. A chat title is the display name, or a name from `~/.cache/grok-contacts` when that index exists. `chats` lists handles and counts, not message text. `recent` and `search` return message text for the chat or query you named. `search` snippets are short. Deletes do not exist.

`mark-read` always exits non-zero and writes nothing, including with `--force`. Messages.app scripting cannot mark a chat read (send, login, and logout only). Setting `message.is_read` in `chat.db` is not a real mark-read: Messages does not sync that flag through iCloud, so the iPhone badge stays. Syncing read state requires private IMCore, often with SIP disabled. This CLI will not do that, and it will not send.

`send` does nothing unless `--force` is present. `--dry-run` resolves the target and does not send, even together with `--force`.

`--to` is a person only (phone, email, or a 1:1 chat name). It never selects a group chat, including a group that merely contains that handle. The send uses a Messages `participant` (one-to-one). If the handle exists only in a group, send exits with `refusing_group` and prints that group's name and guid. Nothing is sent. To message a group on purpose, pass `--chat-guid` with the exact guid. Do not pass both `--to` and `--chat-guid`.

Agents must draft the recipient and the exact text and wait for an explicit yes before `--force`. Never send to a group unless the user named that group. If `grok-desk signature` is set, that line is part of the exact text. This CLI does not append it.

If `~/.config/grok-messages/allowlist` exists, the target must be listed (one phone, email, display name, or chat guid per line). An empty allowlist blocks every send.

The first Messages command needs Automation permission for the calling app to control Messages (System Settings → Privacy & Security → Automation). Error -1743 means that grant is missing. History needs Full Disk Access for Grok Bot and Grok Bot Helper. Send does not.

Do not copy `chat.db` off this Mac.
