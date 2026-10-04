# Apple Desk security audit

**Date:** 2026-10-04  
**Tip:** `f17417a4f33d573219ee3d1c97d2327a7d2f2b7e` (`main`)  
**Repo:** https://github.com/PhillipHolland/apple-desk  
**Auditor:** local source review of this checkout (no live Messages/Mail send, no live `chat.db` dump, no host PII copied here)

This file is a written security review. It does not include message text, phone numbers, email addresses, note bodies, reminder titles, or other personal records from any Mac.

## Scope and constraints

Reviewed for the requested focus areas:

1. Messages send consent, draft-then-yes, 1:1 vs group, mark-read, FDA / `chat.db`, attachment path gating, imsg wraps
2. Mail triage dry-run / `--force`, and whether send is possible
3. Notes / Contacts / Reminders (and sibling) caches under `~/.cache`
4. dry-run vs `--force` boundaries across CLIs
5. Secrets / PII in docs, logs, sample data; untracked `IMPROVEMENT_PLAN` risk
6. Symlink doctor and onboard path traversal / unexpected execution
7. Upcoming anonymous onboard ping (present or planned)
8. Doctor / reindex opening apps or dumping private data

Constraints honored:

- Did **not** merge or implement [PR #2](https://github.com/PhillipHolland/apple-desk/pull/2) (unified CLI / EventKit / Mail send journal).
- Report first. No Critical issue was both unambiguous and small enough to patch in this pass.
- No analytics SDK was added or invented.
- No real personal data was copied into this document.

## Method

Read the public monorepo at `f17417a`: CLI Python/JXA, cache builders, `scripts/onboard.sh`, `SKILL.md`, ethics/onboard/install docs, and offline tests for mail triage, attachment path gating, imsg redaction, new-chat send, and outside-checkout doctor hints. Compared claimed gates (`docs/ETHICS.md`, `SKILL.md`) to the actual argv paths. Searched the tree and GitHub issues for telemetry / `GROK_DESK_NO_TELEMETRY`. Did not execute doctors against a personal Mac and did not open `chat.db`.

Severity uses impact × how easy an already-installed agent or local process can cross the stated gate.

| Severity | Meaning |
| --- | --- |
| Critical | Unauthenticated or ungated outbound send; write of `chat.db`; remote code execution; secrets published in the repo |
| High | Stated dry-run / consent gate can be bypassed, or a second high-value copy of private data is created by default |
| Medium | Integrity or leakage with a remaining gate (`--force`, FDA, opt-in, or explicit path) |
| Low | Defense-in-depth, docs, or permissions polish |
| Info | Intentional design, planned work, or residual risk |

## Executive summary

**No Critical findings** in this tip. Messages send and Mail draft stay behind `--force`. There is no `grok-mail send`. `chat.db` is opened read-only. imsg wraps do not call `send` / `tapback` / `launch` / IMCore. Attachment absolute paths are off by default. Onboard does not upload caches.

The main residual risk is **local agent authority**, not a network attacker:

- Draft-then-yes lives in `SKILL.md`, not in the send CLI. `--force` is sufficient to send.
- Several writes that `docs/ETHICS.md` describes as gated are live without `--force` (Notes create/edit, Calendar create/update, Reminders add/done, Contacts create/update).
- If `calendar-cli` is on `PATH`, `grok-calendar create|update --dry-run` is forwarded and **does not stay dry-run**.
- Default reindex copies iMessage bodies and Notes bodies into `~/.cache` (0700/0600). That is a second store outside Apple's TCC files.

No anonymous onboard ping exists yet. If one is added, keep it count-only and honor `GROK_DESK_NO_TELEMETRY`. Do not invent an analytics SDK.

## Findings

| ID | Severity | Area | Title |
| --- | --- | --- | --- |
| H1 | High | Calendar wrap | `pim_wrap` drops `--dry-run` on create/update when `calendar-cli` is present |
| H2 | High | Messages | Send consent is `--force` only; draft-then-yes is skill policy |
| H3 | High | Caches | Default reindex copies message and note bodies into `~/.cache` |
| H4 | High | Writes | ETHICS “writes stay gated” is not true for several create/edit commands |
| M1 | Medium | Messages | `mark-read --to/--chat-guid` does not select that chat |
| M2 | Medium | Messages | `GROK_MESSAGES_IMSG` / `react --force` can run a substitute binary and print its stdout |
| M3 | Medium | Onboard | Existing executable `~/bin/grok-*` is kept and then run; INSTALL manual `ln -sfn` overwrites |
| M4 | Medium | Notes | `export-md --force` writes any `--out` path the process can write |
| M5 | Medium | Spotlight | `--onlyin ~` or `~/Library` can list AddressBook and other non-blocked Library paths |
| M6 | Medium | Mail | Message `id` lookup can hit the first of 40 mailboxes |
| M7 | Medium | Shortcuts | `~/.cache/grok-shortcuts` is created without 0700 |
| M8 | Medium | Contacts | Cache search prints stored phones on every match |
| L1 | Low | Messages | Allowlist is off by default; name matching is loose |
| L2 | Low | Wraps | `GROK_CALENDAR_CLI` / `GROK_REMINDER_CLI` / `GROK_MESSAGES_IMSG` accept any executable |
| L3 | Low | Docs | Host-only inventory counts remain in `docs/AUDIT.md` |
| L4 | Low | Ignore | `.gitignore` does not name `IMPROVEMENT_PLAN` |
| L5 | Low | Messages | Native `recent`/`search` print bodies; imsg wraps hide them |
| I1 | Info | Mail | No send path; triage is dry-run unless `--force` |
| I2 | Info | Messages | 1:1 vs group, FDA, attachment paths, and imsg argv look correctly gated |
| I3 | Info | Telemetry | No ping present; design notes only |
| I4 | Info | Doctor | Doctors launch apps via JXA; rollups avoid dumping bodies |
| I5 | Info | PR #2 | Out of scope; would add Mail send / EventKit |

---

## 1. Messages

### What is working

**Send gate.** `grok-messages send` exits `needs_force` unless `--force` or `--dry-run`. `--dry-run` wins over `--force` and never calls `Messages.send`. Empty `--text` is refused. Text is capped at 4000 characters. The legacy JXA `op: "send"` is disabled.

**1:1 vs group.** `--to` uses `resolve_person_for_send`, which never returns a group as the target. A handle that exists only in a group is `refusing_group` unless it is a phone/email that may start a **new** 1:1. `--to` plus `--chat-guid` is refused. Group send requires an **exact** `--chat-guid`. Dry-run of a missing handle does not create a chat. Offline tests in `cli/grok-messages/tests/test_new_chat.py` cover this.

**FDA / `chat.db`.** History, search, unread, attachments, and send resolution open `~/Library/Messages/chat.db` as `file:…?mode=ro`. The indexer also sets `PRAGMA query_only=ON`. Failure is `needs_full_disk_access` (exit 5). The code tells operators not to copy `chat.db` elsewhere to “fix” FDA. Send itself does not need FDA.

**Mark-read does not write `chat.db`.** `--force` drives Messages UI (activate, then click an enabled Conversation menu item). Success requires `clicked`, `menuEnabled`, and `frontmost`. Locked screen / screensaver / frontmost loginwindow returns `screen_locked` before activate. Accessibility denial is explicit. The command sets `sent: false` and `wroteDatabase: false`.

**Attachment paths.** Default `attachments` has no absolute path. `--reveal-path` prints the path already stored on the row, rejects relative paths, and warns that the file is private. It does not open, copy, or search the disk. Covered by `test_reveal_path.py`.

**imsg wraps.** `history` and `watch` default to dry-run (print argv, do not exec). `--force` runs only `history --json` or `watch --json` for a resolved chat rowid. Bodies are redacted to `hasText` / `textLength`. Paths need `--reveal-path`. Conversion / send / react / tapback / launch flags are not passed. `react` is 1:1 only, dry-run unless `--force`, and refuses groups. PATH/Homebrew imsg is not searched. Covered by `test_imsg_read.py`.

### H2 — High — send consent is `--force` only

`SKILL.md` requires: draft recipient + exact text, wait for an explicit yes, then `send --force`. The CLI does not enforce that conversation. Any process that can run the binary (Grok Bot Helper, Terminal, a script) can send with `--force` as soon as Automation → Messages is granted.

The optional allowlist (`~/.config/grok-messages/allowlist`) is off when the file is missing. Doctor says `--force` is then the only gate.

**Remediation**

- Keep the skill rule.
- For agents, prefer a two-step CLI: `send --dry-run` prints a nonce; `send --force --confirm TOKEN` expires quickly. Or require the allowlist file to exist (empty file = refuse all) on bot installs.
- Do not treat `--force` as proof that a human said yes.

### M1 — Medium — `mark-read --to` is not that chat

Help text says `--to` / `--chat-guid` clicks Mark as Read when that item is enabled. Implementation resolves the chat only to fail on a bad target, then always sends JXA `mark_front`, which clicks **Conversation → Mark as Read** on whatever thread is frontmost after activate. It does not select the resolved guid.

`--all --force` clicks Mark All as Read. That matches the help.

**Remediation**

- Either implement a select-then-mark path for one chat, or drop `--to`/`--chat-guid` until that exists.
- Until then, document that one-chat mark-read is “frontmost conversation only.”

### M2 — Medium — substitute imsg binary and stdout leak

`GROK_MESSAGES_IMSG` is used if that path is an executable file. There is no checksum, no prefix check, and no restriction to `~/Developer/vendor/imsg`. `--force` on `react` prints vendor stdout/stderr (JSON includes both). A replaced binary can send, write, or print message bodies while this wrap believes it only reacted.

**Remediation**

- Resolve the binary and require it to sit under the vendored imsg checkout (or a signed path).
- Redact `react` stdout the same way history/watch already redact bodies.
- Keep refusing `imsg tapback` / `imsg launch` / IMCore.

### L1 / L5 — Low

Allowlist lines that match a display name apply to every chat with that name. Native `recent` and `search` print message text after FDA; the newer imsg wraps hide text. That split will confuse agents into using `recent` when they meant a metadata-only read.

**Remediation:** allowlist exact guid/handle only; add `recent --bodies` defaulting to off, or document that `recent`/`search` are the body channels.

### I2 — Info

No Critical hole was found in group-send refusal, FDA handling, attachment gating, or imsg argv construction on this tip.

---

## 2. Mail triage

### I1 — Info — no send; mutating cmds are dry-run unless `--force`

`grok-mail` has no `send` subcommand. JXA rejects `op === "send"` or `payload.send`. `draft --force` saves a hidden `OutgoingMessage` and calls `save`, not `send`. `--dry-run` and the default (no `--force`) never call Mail.app. `flag`, `move`, and `mark-read` default to dry-run and require `force: true` in JXA as a second check. Offline `test_triage.py` asserts send is absent and dry-run does not call JXA.

This matches `docs/MAIL_TRIAGE.md` and `docs/ETHICS.md` (“agents must not send Mail”).

### M6 — Medium — mailbox id collision

`show` / triage locate a numeric Mail id by walking up to 40 candidate mailboxes and taking the first hit. Mail ids are not globally unique across accounts. `--mailbox` / `--account` narrow this; without them, `--force` could flag, move, or mark-read the wrong message. The command still does not send.

**Remediation:** require `--mailbox` (and `--account` when names collide) on apply. Refuse apply when more than one mailbox contains that id.

Draft `--to` is a single address string in JXA (comma-splitting exists only on dry-run). Not a send bug.

---

## 3. Caches under `~/.cache`

`docs/ETHICS.md` and `docs/INSTALL.md` say caches stay local, dirs `0700`, databases `0600`, never uploaded. `grok-desk` does not upload. Modes are applied on the paths the desk/notes/contacts/calendar/reminders/safari writers create.

### Inventory (what is stored)

| Cache | Built by | Contents | Default onboard |
| --- | --- | --- | --- |
| `~/.cache/grok-notes/index.sqlite` | `grok-notes reindex` / desk reindex | Folder tree; **full note bodies** up to 200 000 chars; FTS | Yes |
| `~/.cache/grok-messages/index.sqlite` | `grok-desk reindex` | Chat guid, display name, group flag, service, counts; **FTS of message text** up to 8000 chars/row | Yes |
| `~/.cache/grok-contacts/index.sqlite` | reindex `--only contacts` or `--index-contacts` | id, name, org, nickname, relationships, **phones, emails** | Off |
| `~/.cache/grok-calendar/index.sqlite` | desk reindex | Calendar names; event uid/title/start/end/all-day. **No location, no notes** | Yes |
| `~/.cache/grok-reminders/index.sqlite` | desk reindex | Lists; incomplete reminders id/title/due. **No reminder notes** | Yes |
| `~/.cache/grok-safari/` | safari list/search | Bookmark / Reading List titles and URLs (mtime-keyed) | On first safari read |
| `~/.cache/grok-shortcuts/` | shortcut create | Temp unsigned/signed `.shortcut` blobs | On create `--force` |
| `~/.config/grok-desk/signature` | `signature --set` | One outgoing footer line, `0600` | Asked on guided onboard |
| `~/.config/grok-messages/allowlist` | user file | Send targets | Optional |

Not stored: Keychain, passwords, Mail bodies (no mail index), Focus per-app allow lists, Safari history/cookies, `chat.db` copy (indexer reads it, does not copy the file).

### H3 — High — default body caches

`grok-desk onboard` / `reindex` always indexes Notes (full bodies) and Messages (FTS bodies) when those CLIs work. FDA for Messages history is enough to fill the messages FTS. After FDA is later revoked, **the cache still has the text**. Time Machine, other users on the Mac, or a world-readable slip of `~/.cache` would expose a second copy Apple’s Messages TCC no longer covers.

Contacts is correctly opt-in. Calendar/Reminders omit notes and locations.

**Remediation**

- Default messages reindex to metadata-only (guid, name, counts). Add `--index-bodies` for FTS.
- Same split for Notes if a metadata index is enough for first-run search.
- Document that these files are as sensitive as `chat.db` / Notes.app and should be excluded from backups.
- On `cache-clear` / uninstall, delete them.
- Keep 0700/0600. Also chmod `grok-shortcuts` (M7).

### M8 — Medium — contacts cache search prints phones

After opt-in, `grok-contacts search` (cache path) prints the first stored phone on every match. Live search does not. `show` is the documented one-card dump.

**Remediation:** cache search returns name + id only; phones/emails only on `show --id`.

### M7 — Medium — shortcuts cache mode

`_cache_dir()` does `mkdir(parents=True, exist_ok=True)` with no `chmod 0700`. A signed shortcut sitting in `~/.cache/grok-shortcuts` can inherit a permissive umask.

**Remediation:** reuse `common.secure_dir`.

### Leakage residual

0700/0600 is correct for a single-user Mac. It does not protect against the same uid (the agent), root, or backups. Guided onboard `--json` embeds doctor blobs (counts, not bodies). `grok-desk status` prints cache **paths and byte sizes**, not titles. `signature` without `--json` prints the stored line (intended; treat the terminal as sensitive).

---

## 4. dry-run vs `--force` across CLIs

`docs/ETHICS.md`: “Writes stay gated (`--force` or the existing confirm gate).”

### Matrix (this tip)

| CLI | Command | Default | `--dry-run` | `--force` |
| --- | --- | --- | --- | --- |
| grok-messages | send | refuse | resolve only; never sends | send (unless dry-run also set) |
| grok-messages | mark-read / react / history / watch | refuse / dry-run | n/a (no-force is dry-run) | apply / exec |
| grok-mail | draft / flag / move / mark-read | refuse or dry-run | no Mail.app | apply; never send |
| grok-mail | send | **absent** | — | — |
| grok-notes | delete-* / empty-trash / import-md / export-md / promote-checklist | refuse / dry-run | no write | write |
| grok-notes | create-note / create-folder / edit / append / move / duplicate / checklist add | **live write** | none | n/a |
| grok-contacts | delete / delete-group | refuse | none | delete |
| grok-contacts | create / update / group membership | **live write** | none | n/a |
| grok-calendar (JXA) | delete / alarm | refuse / dry-run | no Calendar.app | apply |
| grok-calendar (JXA) | create / update | **live write** unless `--dry-run` | honors dry-run | none |
| grok-calendar (`calendar-cli` wrap) | create / update `--dry-run` | **forwards a real create/update** | **dropped** | n/a |
| grok-reminders (JXA) | delete / flag / move | refuse / dry-run | no Reminders.app | apply |
| grok-reminders (JXA) | add | **live** unless `--dry-run` | honors dry-run | none |
| grok-reminders (JXA) | done | **live** | none | none |
| grok-shortcuts | run / create | refuse | validate only | run or sign |
| grok-focus | set | refuse | validate only | run named shortcut |
| grok-safari | to-note | dry-run | no Notes.app | `grok-notes create-note` |

### H1 — High — calendar wrap discards `--dry-run`

`cli/grok-calendar/bin/grok-calendar` tries `pim_wrap.py` first when `GROK_CALENDAR_CLI`, `calendar-cli` on `PATH`, or `~/.local/bin/calendar-cli` exists. `mapped()` for `create` and `update` never inspects `--dry-run`. `main()` then `subprocess.run`s `calendar-cli create|update …`. The in-house JXA path **does** honor `--dry-run`. An agent that always passes `--dry-run` first is safe only when the wrap is not selected.

Reminders wrap: `add --dry-run` returns no mapped argv (exit 86) and falls through to JXA, which honors dry-run. Flag/move are not mapped and also fall through. Delete still needs `--force`. That path is consistent. PR #2’s note about a reminders wrap dropping `--dry-run` is **not** the current reminders wrap; the calendar wrap is the live hole.

**Remediation (small, do not take EventKit from PR #2)**

- In `cli/grok-calendar/lib/pim_wrap.py`, if `flags.get("dry-run")` on create/update/delete, do not call `calendar-cli` (print a dry-run JSON or fall through with 86).
- Same belt-and-suspenders on reminders wrap for any future mapped mutation.

### H4 — High — ungated writes vs ETHICS

Notes create/edit/append, Calendar create/update (JXA), Reminders add/done, and Contacts create/update mutate the user’s PIM without `--force`. Safari `to-note --force` then calls `grok-notes create-note`, which also has no force check.

This is the largest agent-safety gap after send. A skill that only treats `--force` as dangerous will still create notes, events, reminders, and contacts.

**Remediation:** make those commands dry-run by default and require `--force`, matching mail triage and reminder move/flag. Keep deletes on `--force`.

---

## 5. Secrets / PII in docs and untracked files

Reviewed committed markdown, fixtures, and tests. Public examples use `example.com`, `example.invalid`, `555-0100`, and placeholders (`<account>`, `NOTEID`). Tests in notes/safari explicitly fail if `phillip`, `holland`, `@gmail`, or similar host tokens appear in those fixtures.

`docs/AUDIT.md` / `docs/SCOPE_AUDIT.md` still contain **host-only inventory counts** (people, chats, notes) from a packaging snapshot. They claim not to include message text or addresses. That is still machine-specific telemetry in a public repo.

**L3 — Low:** move those counts to a private note, or keep only versions and “doctors were not re-run.”

**L4 — Low — `IMPROVEMENT_PLAN`:** that name is not in the tree and must not be committed. `.gitignore` does not list it. If a local plan contains host paths, accounts, or message samples, a later `git add .` would publish them.

**Remediation:** add `IMPROVEMENT_PLAN*` (and `*.local.md` if used) to `.gitignore`. Keep using `.env`, `*.pem`, `chat.db*`, `.cache/`, `*.sqlite` as already ignored.

No API keys, tokens, or baked signatures were found in the committed skill or docs. `SKILL.md` correctly says never bake a person’s signature line.

---

## 6. Symlink doctor and onboard

### What is working

`scripts/onboard.sh` uses a hardcoded tool name list (no user path interpolation). It will not rewrite a `~/bin/grok-*` symlink whose resolved target is outside `$ROOT`, and it will not rewrite when `~/Developer/$name` exists. It prints a migrate hint instead. No sudo.

`grok-desk doctor` (`f17417a`) prints hints when the first `PATH` hit for a `grok-*` executable resolves outside this checkout. It does not relink, copy, or execute those binaries. `cli/grok-desk/tests/test_outside_checkout.py` locks that.

`grok-icloud` refuses paths that resolve outside CloudDocs and does not follow escaping symlinks.

### M3 — Medium — keep-and-run, plus INSTALL overwrite

1. `onboard.sh` **keeps** an existing **executable** `~/bin/grok-desk` (even outside the checkout) and then runs `"$HOME/bin/grok-desk" onboard "$@"`. Unexpected code execution is “whatever is already linked,” not a path-traversal from the script’s `src` values.
2. `common.link_if_needed` also keeps an executable dest. Sources are only `~/Developer/apple-desk/cli/…` and `~/Developer/grok-*/bin/…`.
3. `docs/INSTALL.md` “manual equivalent” uses `ln -sfn` unconditionally and **will** replace an outside link. That fights the doctor hint and the onboard.sh warn.

`"$@"` is forwarded to `grok-desk onboard` (intended `--index-contacts` / `--guided`). It is not passed to `eval`.

**Remediation**

- Have onboard.sh refuse to **execute** a `grok-desk` whose realpath is outside `$ROOT`; print the same migrate hint.
- Align INSTALL.md with `link_if_needed` / `symlink_outside_root`.
- Do not copy or relink in doctor (already true).

No symlink-based path traversal that writes outside the repo was found in the linker itself.

---

## 7. Upcoming anonymous onboard ping

**Not present.** Grep of this tip and GitHub issues found no telemetry client, no `GROK_DESK_NO_TELEMETRY`, no HTTP beacon, and no analytics dependency. `docs/ETHICS.md` says nothing is uploaded. Keep it that way until a ping is an explicit product choice.

If a later change adds a first-run ping, do **not** invent a third-party analytics SDK. A single HTTPS POST of a static JSON object is enough.

### Required design (do not implement here)

Allowlist fields only:

- `tool` / `version` (e.g. `grok-desk 0.1.7`)
- `osMajor` (e.g. `26`) — not build, not hardware UUID
- gate **names** that passed or failed (`messages-fda`, `notes`, …) — not Settings output, not doctor JSON
- boolean `contactsIndexOptIn`
- boolean `ok`

Never send: hostname, username, Apple ID, email, phone, chat guid, note title, signature line, PATH, cache paths, counts of people/chats/notes, IP-derived geo.

Rules:

- Default **off** until the user or a documented `--ping` flag opts in, **or** default on only after a one-line prompt on guided onboard.
- Honor `GROK_DESK_NO_TELEMETRY=1` in the environment **and** a file `~/.config/grok-desk/no-telemetry`. Either one suppresses the POST. Document the env var in `SKILL.md` and `docs/ONBOARD.md`.
- Timeout a few seconds, one shot, never retry in a doctor loop, never from `send` / `reindex` body paths.
- Fail open: network errors are silent and do not fail onboard.
- Log only `ping: skipped` / `ping: sent` — never the payload if it ever grows.

---

## 8. Doctor / reindex opening apps or dumping private data

### I4 — Info — doctors launch apps; rollups are count-shaped

`Application("Notes"|"Messages"|"Mail"|…)` in JXA starts the app if it is not running. `grok-contacts doctor --live` also runs `open -ga Contacts`. Guided onboard uses that live Contacts doctor (gate 4). `grok-desk status` / plain onboard run a **5s** doctor on notes, contacts (cache doctor, not `--live`), messages, shortcuts, icloud, spotlight, focus, safari; calendar/reminders get a lean count/names doctor on `status`. Mail stays version-only because Mail doctor can hang.

Doctors return versions, counts, and group/account **names**, not note bodies or message text. `unified_status_doctors` comments that event/reminder titles must not be dumped. `run_cmd` truncates stdout (500 bytes normally; 16 000 on guided).

`grok-notes open` focuses Notes on one note (documented). `mark-read --force` brings Messages frontmost. `shortcuts create --force` without `--output` opens Shortcuts.app.

**Remediation:** document that guided onboard and `*-doctor` may launch those apps. Prefer cache-only contacts doctor on AFK status. Do not add `open` or `activate` to rollup doctors.

### Reindex dump

Reindex is the bulk read:

- Notes: walks Notes.app and writes bodies into sqlite (H3).
- Messages: read-only `chat.db` → FTS bodies (H3). File is not copied.
- Contacts: read-only AddressBook sqlite (FDA-class), opt-in.
- Calendar/Reminders: titles and dates only; doctor timeout → `pending_allow`, no retry loop.

`GROK_CALENDAR_PROGRESS` prints calendar **names** to stderr. Fine for a debug flag; leave it off by default.

---

## Related surfaces (short)

**Spotlight.** Defaults to Documents + Desktop. Blocks path parts `keychains`, `messages`, `mail`, `homekit`, `passes`, `safari`, `cookies`, and password group-containers. Returns paths only. `--onlyin ~` is allowed and is the M5 gap (`AddressBook` is not a blocked part).

**iCloud.** CloudDocs only. No other ubiquity containers. Dataless files are not opened. Symlinks that leave the root are refused.

**Focus.** Reads assertion/configuration JSON; does not read `ModeConfigurationsSecure.json`. `set` never writes the DND database; `--force` only runs a user-named shortcut.

**Safari.** Bookmarks.plist only. No history/passwords/cookies. URLs are not opened. `to-note` is dry-run unless `--force`.

**Shortcuts `run --force`.** The wrapper cannot see the graph. A shortcut can message, call, or toggle Home. That is documented and correctly gated.

**Env-selected helpers.** `GROK_MESSAGES_IMSG`, `GROK_CALENDAR_CLI`, and `GROK_REMINDER_CLI` all exec a caller-chosen binary (L2). Treat them like `$EDITOR`: local trust, not a security boundary.

---

## Out of scope / not done

- **PR #2** (EventKit helper, unified `apple-desk` CLI, Mail send journal, attachment export). Not reviewed as code and not merged. Its own text says it adds **explicit Mail sends**. Re-audit that branch before any merge; do not treat this document as coverage of PR #2.
- **IMPROVEMENT_PLAN** (untracked). Not read, not committed.
- Live TCC dialogs, live send, and live `chat.db` contents.
- Vendor `imsg` / `calendar-cli` / `reminder-cli` source (not in this repo).

## Residual risk

Apple Desk is a **local privileged agent**. Automation + FDA is already enough to read Messages and drive Mail/Notes/Contacts. The CLIs mostly make that honest and add `--force` on the worst writes. They cannot protect a user from an agent that is told to pass `--force`, and they should not claim to.

Highest follow-ups, in order:

1. Fix calendar `pim_wrap` `--dry-run` (H1).
2. Gate Notes/Calendar/Reminders/Contacts creates behind `--force` (H4).
3. Default messages/notes indexes to metadata-only (H3).
4. Tighten send consent beyond a single flag (H2).
5. Fix or document `mark-read --to` (M1).

No Critical patch was applied in this pass.  
<|eos|>