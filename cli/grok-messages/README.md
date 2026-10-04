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

`mark-read` does nothing unless `--force` is present. It does not write `chat.db`, send, type, or press Return. With `--all --force` it first checks that Messages can be in front; if `loginwindow` is frontmost or the screensaver is running, it exits non-zero without activating anything and says that this UI action needs Messages in front. Unread, doctors, and other non-UI Apple Desk commands are not blocked. Otherwise it brings Messages frontmost, waits until Conversation → Mark All as Read is enabled, and clicks that item. Bringing Messages forward without that click is not success. `--to` or `--chat-guid` clicks Mark as Read only when that exact item is enabled. This needs Automation for Messages and Accessibility for System Events. The separate `send` command uses Messages scripting's `send` operation, is independently gated, and was not tested under the lock; mark-read never invokes it. The iPhone badge has to be confirmed on the phone.

`send` does nothing unless `--force` is present. `--dry-run` resolves the target and does not send, even together with `--force`.

`--to` is a person only (phone, email, or a 1:1 chat name). It never selects a group chat, including a group that merely contains that handle. The send uses a Messages `participant` (one-to-one). If the handle exists only in a group, that group is not the target. A phone or email handle plus text can start a separate 1:1. A group name still exits with `refusing_group`. To message a group on purpose, pass `--chat-guid` with the exact guid. Do not pass both `--to` and `--chat-guid`.

A missing 1:1 is created only when `--to` is a phone or email handle and `--text` is non-empty. The Messages dictionary cannot make an empty chat (chats and participants are read-only), so the first message is the creation. `--dry-run` does not send and does not create a chat. `--force` is the only apply path, and it sends once. An existing 1:1 is reused and a second chat is not created. A display name with no 1:1 is still not found. A group name or a group guid is still refused. This does not open the Messages window.

Agents must draft the recipient and the exact text and wait for an explicit yes before `--force`. Never send to a group unless the user named that group. If `grok-desk signature` is set, that line is part of the exact text. This CLI does not append it.

If `~/.config/grok-messages/allowlist` exists, the target must be listed (one phone, email, display name, or chat guid per line). An empty allowlist blocks every send.

The first Messages command needs Automation permission for the calling app to control Messages (System Settings → Privacy & Security → Automation). Error -1743 means that grant is missing. History needs Full Disk Access for Grok Bot and Grok Bot Helper. Send does not.

Do not copy `chat.db` off this Mac.

`attachments` lists metadata for one chat (name, mime, bytes, sticker, date). It does not open, copy, or send the file. Default output has no absolute path. `--reveal-path` prints the local path already stored on that row and warns that the file is private. It does not open the file and does not search the disk. If the row has no path, the command says so and exits cleanly.

```bash
grok-messages attachments --chat-guid "fixture-chat"
grok-messages attachments --chat-guid "fixture-chat" --reveal-path
```

`history` wraps `imsg history`. `watch` wraps `imsg watch`. Both are a dry-run unless `--force`. A dry-run prints the argv and does not run imsg, so it does not print a message body or a path. `--force` still omits message text. imsg has no attachments subcommand. `original_path` on that JSON is printed only with `--reveal-path`, which warns and does not open the file. Attachment conversion is not requested. `send`, `react`, and `mark-read` do not use this wrap.

```bash
grok-messages history --chat-guid "fixture-chat"
grok-messages history --chat-guid "fixture-chat" --force
grok-messages watch --chat-guid "fixture-chat"
```

