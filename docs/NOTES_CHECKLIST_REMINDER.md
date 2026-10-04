# Checklist line to one reminder

`grok-notes promote-checklist` prepares one reminder from one checklist line. Dry-run is the default. `--force` is the only path that creates a reminder. The checklist line is left unchanged. The command does not mark the line done.

`--force` calls the existing `grok-reminders add` path (Reminders.app JavaScript for Automation).

## Pick a line

`grok-notes checklist show --id NOTEID` numbers the lines. `--index` is that number, starting at 1. `--text` must match one line exactly. Pass one of `--index` or `--text`.

```text
checklist:
  1. [ ] Pack bag
  2. [ ] Pack bag
  3. [ ] Lock door
```

`--index 1` is the first `Pack bag`. `--text "Lock door"` is the only line with that text. `--text "Pack bag"` matches two lines, exits 2, and creates nothing:

```text
grok-notes: ambiguous
More than one checklist line has that exact text. Pass --index. Nothing was created.
```

Use `--index` for that line. Passing both `--index` and `--text` exits 2 before Notes is read.

## Dry-run

```bash
grok-notes promote-checklist --id NOTEID --index 1
```

For a note titled Packing list, that prints:

```text
dry-run: would add one reminder 'Pack bag'
note: Packing list
id: NOTEID
due: none
checklist line left unchanged (checked state is not reliable; the backlink is on the reminder)
dry-run: Notes was only read. Reminders.app was not called. Pass --force to add one reminder. The checklist line is not marked done.
```

Notes is only read. The dry-run creates nothing. The checklist line is left unchanged.

`--text "Lock door"` prints the same shape with that line. Add `--due 2026-10-04` only when the reminder should have a due date. The dry-run then prints `due: 2026-10-04`. On `--force`, a date with no time is stored at 09:00 local by `grok-reminders add`. Omit `--due` and no due date is set. `--list` is a Reminders list name. Omit it and add uses the default list.

## Apply

The same selection with `--force` is the create:

```bash
grok-notes promote-checklist --id NOTEID --index 1 --force
```

That prints `added reminder 'Pack bag'` and `The checklist line was not changed.`

## Backlink

The reminder title is the checklist line (`Pack bag`). The reminder notes are plain text, on the reminder:

```text
Backlink
title: Packing list
id: NOTEID
```

The text dry-run names the note and the id, and says the backlink is on the reminder. `--json` includes that block as `reminder.notes`. The link-a-note control is not scriptable, so the backlink stays plain text on the reminder. The checklist line is left unchanged.
