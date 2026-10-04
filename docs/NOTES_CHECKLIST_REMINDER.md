# Checklist line to one reminder

`grok-notes promote-checklist` prepares one reminder from one checklist line. Dry-run is the default. `--force` is the only apply path.

The dry-run reads the note and does not call a Reminders write. It does not create a reminder. `--force` calls the existing `grok-reminders add` path (Reminders.app JavaScript for Automation). This is not a second reminders backend, not RemCTL, and not EventKit.

## Command

```bash
grok-notes promote-checklist --id NOTEID --index 1
grok-notes promote-checklist --id NOTEID --text "Pack bag"
grok-notes promote-checklist --id NOTEID --text "Pack bag" --due "2026-10-04"
grok-notes promote-checklist --id NOTEID --index 1 --list "Reminders" --force
```

`--index` is 1-based and matches `grok-notes checklist show`. `--text` must match one line exactly. If two lines share that text, pass `--index`. Pass `--due` only when the reminder should have a due date. A date with no time is stored at 09:00 local by `grok-reminders add`. Omit `--due` and no due date is set.

The reminder title is that checklist line. The reminder notes contain a backlink with the note title and the note id:

```text
Backlink
title: Packing list
id: NOTEID
```

## What this does not do

The checklist line stays as it is. Checked-state is flaky: Notes rewrote `checked`, `done`, and `class` off `<li>` on write, so this command does not try to mark the line done. The backlink lives on the reminder.

The link-a-note control is not in the Notes scripting dictionary, so the backlink is plain text. It is not a Notes link object.

`promote-checklist` does not add a checklist item, edit the note, or move the note. After `--force`, the search index is unchanged until `grok-notes reindex`. Reminders sections and smart lists are still not scriptable.
