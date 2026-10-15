# Apple Desk

Let an AI agent read and (with your yes) act on Messages, Notes, Calendar, Reminders, and the rest of your Mac — locally, through shell CLIs. No cloud Apple API.

<!-- TODO: add a short demo GIF at docs/demo.gif (first win: grok-messages unread). Do not fabricate one. -->

**Roadmap (not built):** a single MCP server. Today every surface is a `grok-*` CLI you run in a shell. See [`mcp/README.md`](./mcp/README.md).

## Example agent prompts

- "Show my unread iMessage counts. Draft a reply to that 1:1 chat — do not send until I say yes."
- "What reminders are due today, and add one to pack for tomorrow (dry-run first)."
- "Find my note titled Lease and append the new address as a dry-run."

## Requirements

| Need | Minimum (from this tree) |
| --- | --- |
| macOS | **13 Ventura or later.** There is no `sw_vers` check. `osascript -l JavaScript` (JXA) drives Notes, Messages send, Calendar, Reminders, Contacts, and Mail. `/usr/bin/shortcuts` needs macOS 12+. Focus reads the Monterey-era Do Not Disturb database. |
| Python | **3.9+** (`python3` on PATH). Shebangs are `#!/usr/bin/env python3`. The code uses `str.removeprefix` and `from __future__ import annotations`. |
| JXA | **`osascript` with JavaScript.** Required for every Apple-app CLI except path-only tools (Spotlight, iCloud list/read, Safari bookmarks plist, Focus DB). |
| Automation | System Settings → Privacy & Security → **Automation** → allow the app that runs the CLI (Grok Bot, Grok Bot Helper, or Terminal) for each Apple app you use. |
| Full Disk Access | System Settings → Privacy & Security → **Full Disk Access** to read Messages history (`~/Library/Messages/chat.db`). **Send does not need FDA.** |

No Homebrew formula. No sudo.

## 60-second quickstart

```bash
# Skip the one anonymous onboard ping: GROK_DESK_NO_TELEMETRY=1
curl -fsSL https://raw.githubusercontent.com/PhillipHolland/apple-desk/main/scripts/install.sh | bash
# new terminal, or:
export PATH="$HOME/bin:$HOME/.local/bin:$PATH"
grok-messages unread
```

The installer links the CLIs, writes `~/bin` and `~/.local/bin` into your shell rc, then runs `grok-desk onboard --guided --quick`. Linking and PATH finish even if a doctor gate fails. If onboard stops, fix the printed System Settings path and re-run `grok-desk onboard --guided`.

**Success looks like:** unread message count, unread chat count, and a short page of chat labels. No message text. Nothing is marked read.

If that command exits 3, 4, 5, -1743, or -1712, follow the printed System Settings path once, then re-run the same command. Do not loop while AFK.

`--quick` walks the same permission gates and then indexes Messages metadata only, so you are not left staring at a silent 20+ minute Calendar walk. Full indexes later: `grok-desk reindex`.

Manual clone and doctor matrix: [`docs/INSTALL.md`](./docs/INSTALL.md). Guided gates: [`docs/ONBOARD.md`](./docs/ONBOARD.md). Agent skill: [`SKILL.md`](./SKILL.md).

## Privacy and safety

- **Local-only caches.** Indexes live in `~/.cache/grok-*` (directories `0700`, databases `0600`). Note text, contacts, and message bodies are not uploaded.
- **`chat.db` is read-only.** History, unread, and search read `~/Library/Messages/chat.db`. The CLIs never write it.
- **Sends wait for you.** `grok-messages send` without `--force` is a dry-run and prints a confirm token. The only send is `--force --confirm TOKEN` after a human yes. `--force` alone does not send.
- **1:1 only.** `--to` never targets a group. Groups need `--chat-guid` after you name that group.
- **Deletes need `--force`.** Notes, calendar, reminders, and contacts writes stay a dry-run unless `--force`.
- **One anonymous onboard ping.** After a successful `grok-desk onboard --guided`, or the first successful `grok-desk status`, the CLI may send one GET to `https://apple-desk-counter.vercel.app/onboard` (no query, no body, no machine id, no path, no signature). `GET https://apple-desk-counter.vercel.app/count` reads the total and does not increment. Opt out: `GROK_DESK_NO_TELEMETRY=1`. A failed request is ignored; a local marker is written only after HTTP 2xx.

Apple Desk is not an Apple product. Nobody else endorses it.

## CLIs (under `cli/`)

| CLI | Role |
| --- | --- |
| `grok-desk` | Onboarding, local indexes, signature |
| `grok-messages` | Unread, history, gated 1:1 send, react |
| `grok-notes` | Notes.app + search cache, markdown import/export |
| `grok-reminders` | Reminders.app (dry-run add unless `--force`) |
| `grok-calendar` | Calendar.app (cache-first list/search) |
| `grok-contacts` | Contacts.app (cache-first; `--live` for the app) |
| `grok-shortcuts` | List / run / create (`run` and `create` need `--force`) |
| `grok-mail` | Mail.app reads and gated draft (prefer a cloud mail connector) |
| `grok-icloud` | iCloud Drive list/read/summary (no force-download) |
| `grok-spotlight` | Scoped `mdfind` (paths only) |
| `grok-focus` | Focus status (best-effort; `set` needs `--force` and a shortcut) |
| `grok-safari` | Safari bookmarks + Reading List (read-only plist) |

## Messages send rules

- Never send without user pre-approval of recipient + exact text, including the signature line when one is set.
- Never resolve a person to a group chat (`--to` is 1:1 only).
- Groups need `--chat-guid` after the user named that group.
- Signature is `grok-desk signature` (`~/.config/grok-desk/signature`). The send CLI does not append it.

## CLI versions

Source `VERSION` strings in this checkout. Full command lists: [`docs/COVERAGE.md`](./docs/COVERAGE.md).

| CLI | Version |
| --- | --- |
| `grok-desk` | 0.1.10 |
| `grok-messages` | 0.2.14 |
| `grok-notes` | 0.2.4 |
| `grok-reminders` | 0.1.6 |
| `grok-calendar` | 0.1.7 |
| `grok-contacts` | 0.1.4 |
| `grok-shortcuts` | 0.1.2 |
| `grok-mail` | 0.1.3 |
| `grok-icloud` | 0.1.1 |
| `grok-spotlight` | 0.1.0 |
| `grok-focus` | 0.1.1 |
| `grok-safari` | 0.1.3 |

## Principles

Apple Desk runs on the user's Mac, for that user.

- Local only. Indexes stay in `~/.cache/grok-*`. Nothing uploads `chat.db`, contacts, notes, or message text.
- Permission is honest. Full Disk Access is what lets a process read Messages history. Automation Allow is what lets a process control an app. A timeout is a hang or a dialog still on screen, not proof the user clicked Deny.
- Outbound and destructive actions wait. Draft the recipient and the exact text, then send only after an explicit yes and `grok-messages send --force --confirm TOKEN`.
- The agent acts for the user. It does not message, mail, or change data on its own.

## OSS neighbors

Credit only. Nothing here is vendored, and this project does not copy their source. Apple Desk is in-house. It is not an Apple product, and none of these projects endorse it.

Patterns worth learning from them: EventKit is a better long-term path than AppleScript for Calendar and Reminders; say which TCC grant you actually need; prefer a `status` or `doctor` plus `--json`. We still talk to Calendar and Reminders through the apps today. Switching those reads to EventKit is future work, not a copy of anyone's tree.

- [openclaw/openclaw](https://github.com/openclaw/openclaw) and [openclaw/imsg](https://github.com/openclaw/imsg) — iMessage over a local JSON-RPC CLI (`brew install steipete/tap/imsg`). We read `chat.db` ourselves and send only through Messages.app after an explicit yes.
- [omarshahine/Apple-PIM-Agent-Plugin](https://github.com/omarshahine/Apple-PIM-Agent-Plugin) — EventKit Swift CLIs aimed at OpenClaw.
- [tonyhth/openclaw-apple-calendar](https://github.com/tonyhth/openclaw-apple-calendar) — calendar bridge for OpenClaw.
- [danielhopkins/apple-tools](https://github.com/danielhopkins/apple-tools) — MIT. Closest peer. See `prior-art.md` in that repo.
- [54yyyu/pyapple-mcp](https://github.com/54yyyu/pyapple-mcp), [krmj22/macos-mcp](https://github.com/krmj22/macos-mcp), [more-io/claude-apple-bridges](https://github.com/more-io/claude-apple-bridges) — other public MCP or bridge shapes. We do not import them.

Do not vendor or copy proprietary third-party source into this repo.

## License

[MIT](./LICENSE). Copyright Phillip Holland 2026.

## Contributing

See [`CONTRIBUTING.md`](./CONTRIBUTING.md).
