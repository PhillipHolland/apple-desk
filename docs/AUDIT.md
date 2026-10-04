# Apple Desk audit

Checked 2026-10-03 about 12:45 PM CT on this Mac (macOS 27.0, build 26A5388g).
Machine role: office Mac the agent shells into. No iMessages sent. No notes, contacts, reminders, or chats created or deleted.
This file is the packaging snapshot. It does not include message text, phone numbers, emails, note bodies, or reminder titles.

## Install layout

This checkout is the public monorepo https://github.com/PhillipHolland/apple-desk. Each CLI is `cli/<name>/bin/<name>`. Install links those files into `~/bin` and `~/.local/bin` when a link is missing or broken (`docs/INSTALL.md`). Versions below are the `VERSION` string in each CLI. Doctors were not re-run for this edit.

| Tool | Source version | Path in this checkout |
| --- | --- | --- |
| grok-desk | 0.1.7 | `cli/grok-desk/bin/grok-desk` |
| grok-reminders | 0.1.5 | `cli/grok-reminders/bin/grok-reminders` |
| grok-notes | 0.2.3 | `cli/grok-notes/bin/grok-notes` |
| grok-contacts | 0.1.3 | `cli/grok-contacts/bin/grok-contacts` |
| grok-messages | 0.2.11 | `cli/grok-messages/bin/grok-messages` |
| grok-calendar | 0.1.6 | `cli/grok-calendar/bin/grok-calendar` |
| grok-shortcuts | 0.1.2 | `cli/grok-shortcuts/bin/grok-shortcuts` |
| grok-mail | 0.1.3 | `cli/grok-mail/bin/grok-mail` |
| grok-icloud | 0.1.1 | `cli/grok-icloud/bin/grok-icloud` |
| grok-spotlight | 0.1.0 | `cli/grok-spotlight/bin/grok-spotlight` |
| grok-focus | 0.1.1 | `cli/grok-focus/bin/grok-focus` |
| grok-safari | 0.1.2 | `cli/grok-safari/bin/grok-safari` |

There is no separate `~/Developer/grok-notes`, `~/Developer/grok-contacts`, or `~/Developer/grok-messages` tree in this checkout. RemCTL stays an upstream binary. Do not vendor it.

## Safe reads this pass (2026-10-03, not re-run)

That day's `grok-notes`, `grok-contacts`, and `grok-messages` doctors were ok, with Automation authorized and Messages history available. Those binaries were pre-monorepo links under `~/Developer/grok-notes`, `~/Developer/grok-contacts`, and `~/Developer/grok-messages`, not `cli/` in this repo. RemCTL (`remctl` 2.3.0 at `~/bin/remctl`, also `remctl-permissions`) was an upstream MacStories install, doctor ok with 0 failures and 2 warnings. Capability Host was `~/Applications/RemCTL Capability Host.app`, signed, protocol 2, Reminders + Automation + Full Disk Access authorized, effective route `capabilityHost`, ready. Counts below are that snapshot.

| Command | Time | Result |
| --- | --- | --- |
| `remctl doctor --for-agent --json` | 1.16s | effective access ready |
| `remctl --format json stats` | 0.97s | 5 lists, 694 reminders (8 active, 686 completed), 0 overdue, 22 sections |
| `remctl --format json lists` | 0.83s | 5 lists |
| `grok-notes doctor --json` | 0.30s | Notes 4.13, 2 accounts, 47 folders, index 1215 notes |
| `grok-notes status --json` | 0.07s | index schema 1, incremental, 0 warnings, indexed 12:21 PM CT |
| `grok-notes folders --cached --json` | 0.07s | cache hit |
| `grok-notes search "marriage" --limit 5 --json` | 0.08s | cache, 9 total hits (same count as the earlier live walk) |
| `grok-contacts doctor --json` | 1.04s | Contacts 14.0, 3245 people, 1 group, Me card present (name not printed) |
| `grok-contacts groups --json` | 0.35s | 1 group |
| `grok-messages doctor --json` | 0.22s | Messages 26.0, 137 scripting chats, chat.db 169 chats / 63 primary / 6223 messages |
| `grok-messages chats --limit 3 --json` | 0.08s | primary iMessage rows returned; handles not copied here |

`remctl stats --format json` (flag after the subcommand) fails. Use `remctl --format json <cmd>`. Trailing `--json` worked for `remctl doctor --for-agent`.

Writes were not re-run. Create, edit, and delete commands are present in each CLI (see gaps). A future demo must use a throwaway object and must not call `empty-trash` or `send` without `--dry-run` unless the user named the recipient and the text.

## Permissions

- Reminders: Capability Host authorized for Reminders, Automation (Reminders), and Full Disk Access. No extra click.
- Notes: Automation authorized. Cache `~/.cache/grok-notes` is mode 0700, sqlite mode 0600. NoteStore.sqlite is unused on purpose.
- Contacts: Automation authorized. No CNContactStore privacy prompt (by design).
- Messages: Automation authorized. `chat.db` readable by this agent process (6223 rows, read-only). `~/.config/grok-messages/allowlist` does not exist, so `--force` is the only send gate. Nothing was sent.

## RemCTL warnings (not blockers)

1. `~/.zsh/completions` is not on zsh fpath.
2. RemCTL MCP is not connected to Claude Code or Codex. Grok Bot uses the shell CLI. Do not treat that warning as a failure.

## CRUD present vs honest gaps

Reminders in this checkout are `grok-reminders` 0.1.5 (`lists`, `today`, `upcoming`, `search`, `show`, `add`, `done`, `delete`, `flag`, `move`). `add`, `flag`, and `move` stay dry-run unless `--force`. Sections and smart lists are not on this JXA path. The 2026-10-03 RemCTL binary is a separate upstream tool, not a CLI in this repo. Calendar and Mail are their own CLIs in `cli/`.

Notes: create/edit/append/move/delete note and folder, checklist add, attachment list, share flag read, cached search. Cannot pin, lock, toggle checklist checked, duplicate, drawings/scans/tables/audio, attachment bytes, real tag objects, start a share. `pin`/`lock` commands exist and exit unsupported.

Contacts: create/update/delete person, groups, membership. Phone, email, and relationship search use the index only. Cannot merge, photos, vCard import/export, smart lists, or Medical ID. `show` returns phones and emails.

Messages: list, recent, search, unread counts (no message text), attachment metadata, dry-run plain-text send, 1:1 `react` (dry-run unless `--force`), and `mark-read` (does not write `chat.db`). `--to` is 1:1. Groups need `--chat-guid`. A missing 1:1 is created only when `--to` is a phone or email and the text is non-empty, and only `--force` sends it. Cannot make an empty chat, effects, edits, unsends, or pin/mute. History is chat.db, not AppleScript.

## Packaging

One skill: Apple Desk (`SKILL.md`). The public repo is https://github.com/PhillipHolland/apple-desk. Clone it to `~/Developer/apple-desk`. Symlinks in `~/bin` and `~/.local/bin` should point at `cli/<name>/bin/<name>` in that checkout. RemCTL stays `github.com/viticci/remctl` (credit MacStories / Viticci). Do not commit caches, chat.db, or contact exports.
