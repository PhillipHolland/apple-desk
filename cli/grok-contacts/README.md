# grok-contacts

Apple Contacts CLI for any Mac. Default reads use `~/.cache/grok-contacts/index.sqlite` when that index is present and ok (`grok-desk reindex --only contacts`). Pass `--live` to ask Contacts.app with `osascript -l JavaScript` (JXA). It does not use CNContactStore.

```bash
grok-contacts doctor
grok-contacts doctor --live
grok-contacts search "Ada"
grok-contacts search "Ada" --live
grok-contacts show --id CONTACTID
grok-contacts groups
grok-contacts gaps

grok-contacts create --first "Ada" --last "Lovelace" --phone "mobile:555-0100" --email "work:ada@example.com" --group "Engineers"
grok-contacts update --id CONTACTID --org "Analytical Engines" --add-phone "work:555-0199"
grok-contacts add-to-group --id CONTACTID --group "Engineers"
grok-contacts remove-from-group --id CONTACTID --group "Engineers"
grok-contacts delete --id CONTACTID --force
grok-contacts create-group "Engineers"
grok-contacts delete-group "Engineers" --force
```

Add `--json` on any command. `doctor` without `--live` reports the index people count and does not open Contacts.app. `doctor --live` checks the app version and group count/names only. It does not walk every person or open the Me card. `search` and `show` are cache-first. `--field phone` and `--field email` search the index only and never call Contacts. `groups` (and `list`) are still live, because the index stores people, not groups. Deletes need `--force`. Deleting a group with more than 30 members also needs `--allow-large`. Deleting a group does not delete the people in it.

The first live Contacts command needs Automation permission for the calling app to control Contacts (System Settings → Privacy & Security → Automation). Error -1743 means that grant is missing. A dialog that says “Grok Bot” wants access to control “Contacts” is that prompt: click Allow. A timeout is not retried.
