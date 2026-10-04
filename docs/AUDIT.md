# Apple Desk audit

Checked 2026-10-03 about 12:45 PM CT on this Mac (macOS 27.0, build 26A5388g).
Machine role: office Mac the agent shells into. No iMessages sent. No notes, contacts, reminders, or chats created or deleted.
This file is the packaging snapshot. It does not include message text, phone numbers, emails, note bodies, or reminder titles.

## Install layout (not a git repo yet)

| Tool | Version | Binary | Project | Doctor |
| --- | --- | --- | --- | --- |
| RemCTL (`remctl`, aliases `rctl`, `reminders`) | 2.3.0 | `~/bin/remctl` (also `remctl-permissions`) | Upstream MacStories install, not under `~/Developer` | ok, 0 failures, 2 warnings |
| grok-notes | 0.2.0 | `~/bin/grok-notes` → `~/Developer/grok-notes/bin/grok-notes` (same link in `~/.local/bin`) | `~/Developer/grok-notes` | ok, Automation authorized |
| grok-contacts | 0.1.0 | `~/bin/grok-contacts` → `~/Developer/grok-contacts/bin/grok-contacts` | `~/Developer/grok-contacts` | ok, Automation authorized |
| grok-messages | 0.1.0 | `~/bin/grok-messages` → `~/Developer/grok-messages/bin/grok-messages` | `~/Developer/grok-messages` | ok, Automation authorized, history available |

Capability Host: `~/Applications/RemCTL Capability Host.app`, signed, protocol 2, Reminders + Automation + Full Disk Access authorized. Effective route `capabilityHost`, ready.

None of the three `grok-*` trees has a `.git` directory or a remote. RemCTL stays an upstream binary. Do not vendor it into a public repo unless the license says so.

## Safe reads this pass

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

Reminders (RemCTL hosted commands include add, edit, done, undone, delete, restore, lists, groups, sections, smart lists, templates, flag, search, today, upcoming, subtasks, move): broad CRUD. Not in this CLI: Apple Calendar, Mail. Sharing is read (`sharees`), not an invite flow verified here. Pinned list flag exists (`list-pin` / `list-unpin`).

Notes: create/edit/append/move/delete note and folder, checklist add, attachment list, share flag read, cached search. Cannot pin, lock, toggle checklist checked, duplicate, drawings/scans/tables/audio, attachment bytes, real tag objects, start a share. `pin`/`lock` commands exist and exit unsupported.

Contacts: create/update/delete person, groups, membership. Cannot search by phone or email, merge, photos, vCard import/export, smart lists, Medical ID. `show` is the only command that returns phones and emails.

Messages: list, recent, search, dry-run, plain-text send to an existing scripting chat with `--force`, or a missing 1:1 when a phone or email handle and the first message were both named. That first message is the creation. Dry-run does not create a chat. Cannot make an empty chat, groups, attachments, tapbacks, effects, edits, unsends, pin/mute/read. History is chat.db, not AppleScript.

## Packaging

One skill: Apple Desk. When a public GitHub URL is shared, clone it to `~/Developer/apple-desk` and point `~/bin/grok-notes`, `grok-contacts`, and `grok-messages` at that checkout. Until then these three trees are the source. RemCTL stays `github.com/viticci/remctl` (credit MacStories / Viticci). Do not commit caches, chat.db, or contact exports. NotesCTL (Viticci) replaces grok-notes only after that repo is actually public.
