# Contacts phone and email lookup

`grok-contacts search` looks up a person by name, phone, email, nickname, or relationship. Phone, email, and relationship use the local index only. This does not add a second database, and it does not export the address book.

```bash
grok-contacts search QUERY --field phone
grok-contacts search QUERY --field email
grok-contacts search QUERY --field nickname
grok-contacts search spouse --field relationship
grok-contacts search QUERY --field name
grok-contacts search QUERY
```

`QUERY` is a substring of at least 2 characters. Phone and email match the text stored for that field. Name (the default) also matches organization. Matching is case-insensitive.

## Turn the index on once

The index is off by default. It is a local cache of id, name, organization, nickname, relationships, phones, and emails under `~/.cache/grok-contacts`. A normal onboard does not build it. Indexes built before nickname and relationship were stored still answer name, phone, and email. They omit those two fields until the next reindex.

```bash
grok-desk reindex --only contacts
# or during guided setup:
grok-desk onboard --guided --index-contacts
```

## What each flag does

- `--field phone` and `--field email` read the index and never call Contacts.app.
- `--field nickname` reads the nickname column. `--live` asks Contacts.app, because nickname is a person property `whose()` can filter.
- `--field relationship` reads related-name labels in the index (parent, spouse, sibling, friend, manager, and any other label already stored). `sibling` also matches brother and sister. `parent` also matches mother and father. It never calls Contacts.app. `whose()` has no relatedNames property, the same kind of limit as phones (error -2700).
- `--live` with `--field phone`, `--field email`, or `--field relationship` exits `unsupported_field`. This CLI does not walk every card.
- `--live` with the default name field, or with `--field nickname`, asks Contacts.app.
- With no index, phone, email, and relationship search exit `unsupported_field` and do not call Contacts. Name and nickname search fall through to Contacts.app.
- `show` returns nickname and relationships when the read already has them. Empty stays empty. `show --live` reads them from the card. A cache show uses the index and says when those columns are not there yet. `doctor` without `--live` reports the index and does not open Contacts.app.

`grok-contacts --help` and `grok-contacts search --help` show the same commands.
