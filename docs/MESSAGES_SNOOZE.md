# Snooze a Messages chat

Snooze a chat by creating a Reminder whose notes contain the chat guid. Use `grok-messages` and `grok-reminders` only. There is no extra app. This does not send a message and does not mark the chat read.

## Find the guid

`chats` and `list` are read-only.

```bash
grok-messages chats
grok-messages list
```

Copy the guid of the chat to snooze.

## Create the reminder

`grok-reminders add` writes unless `--dry-run`. Show the dry-run first. Run the real create only after the user says yes. Add has no `--force` switch. Omitting `--dry-run` is what writes.

```bash
grok-reminders add --title "Reply in Messages" --notes "$(cat <<'EOF'
chat-guid: CHAT_GUID
EOF
)" --dry-run
```

After an explicit yes, run the same command without `--dry-run`:

```bash
grok-reminders add --title "Reply in Messages" --notes "$(cat <<'EOF'
chat-guid: CHAT_GUID
EOF
)"
```

Replace `CHAT_GUID` with the guid from `chats` or `list`. The notes must contain a line `chat-guid: <guid>`. Do not send. Do not mark the chat read.
