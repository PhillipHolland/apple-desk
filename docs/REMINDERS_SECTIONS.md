# Reminders sections and smart lists

Sections and smart lists are not scriptable on this JXA path. `grok-reminders` talks to Reminders.app with `osascript -l JavaScript`. It is not RemCTL and not EventKit. There is no section command and no smart-list command. This doc does not add one.

Create sections and smart lists yourself in Reminders, or run a Shortcut you already have. This repo does not ship a new app or a new Shortcut, and it does not wrap a third-party API.

## What is missing

`grok-reminders gaps` already records that smart lists, sections, tags, and subtasks are absent. Recurrence is also not available on this JXA path, and EventKit is not in this build. These commands do not exist:

- `section`, `add-section`, or `move --section`
- `smart-list` or any filter whose meaning is "flagged OR due today"
- a recurrence or repeat flag on `add`

Do not invent a JXA call for them.

## Do it in Reminders

Use a standard list. A smart list cannot hold sections.

Sections are headings inside one list. On this Mac, open that list in Reminders and add a section from the list menu (New Section). Name them for how you work, for example Today, Next, and Waiting. The section is only a heading. `grok-reminders` cannot create a section, rename one, or place a reminder in one.

Smart lists are saved filters in the sidebar. Add one with the sidebar add control, choose Smart List, and set the filters Reminders offers, such as date, flag, priority, or list. A useful custom Today is reminders that are flagged or due today. Built-in smart lists such as Today, Scheduled, and Flagged belong to the app. This CLI cannot create, edit, or query them.

If you already have a Shortcut that opens Reminders or adds a reminder to a named list, run that Shortcut yourself. Do not expect this checkout to install one. Shortcuts here are not a way to script sections or smart lists.

## What this CLI can do instead

These commands exist in grok-reminders 0.1.5. `done` is the complete command. There is no `complete` subcommand. `flag` and `move` stay a dry-run unless you pass `--force`. A dry-run does not call Reminders.app. `delete` also exists and refuses without `--force`. It is one id only, and it is not a section tool.

```bash
grok-reminders doctor
grok-reminders lists
grok-reminders today
grok-reminders upcoming --days 7
grok-reminders search "query"
grok-reminders show --id REMINDERID
grok-reminders add --title "Call office" --list "Reminders" --due "2026-10-04 09:00" --priority high
grok-reminders done --id REMINDERID
grok-reminders flag --id REMINDERID --state flagged
grok-reminders flag --id REMINDERID --state unflagged --force
grok-reminders move --id REMINDERID --to "Example"
grok-reminders move --id REMINDERID --to "Example" --force
grok-reminders delete --id REMINDERID --force
grok-reminders gaps
```

Use a separate list when you would have used a section. `move --to` changes the list name, not a section, and only `--force` applies it.

`today` is incomplete reminders whose due day is today. It is not a smart list. Flagged reminders with no due date are not in `today`. `upcoming` is incomplete reminders due from today through N days (default 7). Rows those commands print can show a flagged marker. `flag` sets or clears that flag. Nothing in this CLI returns "flagged OR due today". For that filter, use the smart list you created in Reminders.

Examples use placeholders only. Do not put real reminder titles, account names, or other personal data in this doc.
