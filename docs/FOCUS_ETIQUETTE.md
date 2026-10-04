# Focus etiquette

Before an outbound send or react, the draft confirmation must include the output of `grok-focus status`.

Focus filters the sender's UI more than the recipient's notifications.

```bash
grok-focus status
```

Paste that output into the draft, next to the recipient and the exact text. Wait for an explicit yes, then send or react with the existing command.

Do not block the send. Do not refuse `--force` because Focus is on. Do not activate Messages. Do not call `grok-focus set`.
