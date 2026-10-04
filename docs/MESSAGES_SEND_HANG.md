# Messages send hang

Use this when a 1:1 send worked yesterday and hangs today. Five minutes. Not an investigation.

1. Quit Messages and open it once.
2. Run `grok-messages doctor`.
3. Run one dry-run: `grok-messages send --to PERSON --text "EXACT" --dry-run`. A dry-run does not script Messages when that chat is already resolved from chat.db. It prints a confirm token.
4. After an explicit yes for that recipient and that exact text, one real send: `grok-messages send --to PERSON --text "EXACT" --force --confirm TOKEN`.
5. Stop. Do not loop the send.

Exit 4 (`automation_timeout`) with no Allow dialog is the same first step: quit Messages and open it once, then retry that same command once. If an Allow dialog is on screen, click it once instead. Do not start a long dig before that.

`--unstick-once` is off unless you pass it. On a real send it quits Messages, opens it once, and retries that same send once after a timeout. It does not loop. A dry-run never quits Messages.

An existing 1:1 is reported `sent: true` only after a read-only look at chat.db finds a new outgoing row of that text. If the row is missing, the error is `send_unconfirmed` and `sent` is false. The send script itself is unchanged.

Nothing in this checklist sends a message except step 4, and only after the yes.
