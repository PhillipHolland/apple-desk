# Contacts phone and email lookup

`grok-contacts search` already looks up a person by name, phone, or email. Phone and email use the local index only. This does not add a database, and it does not export the address book.

```bash
grok-contacts search QUERY --field phone
grok-contacts search QUERY --field email
grok-contacts search QUERY --field name
grok-contacts search QUERY
```

`QUERY` is a substring of at least 2 characters. Phone and email match the text stored for that field. Name (the default) also matches organization. Matching is case-insensitive.

## Turn the index on once

The index is off by default. It is a local cache of id, name, organization, phones, and emails under `~/.cache/grok-contacts`. A normal onboard does not build it.

```bash
grok-desk reindex --only contacts
# or during guided setup:
grok-desk onboard --guided --index-contacts
```

## What each flag does

- `--field phone` and `--field email` read the index and never call Contacts.app.
- `--live` with `--field phone` or `--field email` exits `unsupported_field`. Contacts scripting cannot filter those fields, and this CLI does not walk every card.
- `--live` with the default name field asks Contacts.app.
- With no index, phone and email search exits `unsupported_field` and does not call Contacts. Name search falls through to Contacts.app.
- `show --id` reads one card. `doctor` without `--live` reports the index and does not open Contacts.app.

`grok-contacts --help` and `grok-contacts search --help` show the same commands.
