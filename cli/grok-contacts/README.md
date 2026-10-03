# grok-contacts

Apple Contacts CLI for this Mac. It talks to Contacts.app with `osascript -l JavaScript` (JXA). It does not use CNContactStore and it does not read the AddressBook sqlite files.

```bash
grok-contacts doctor
grok-contacts groups
grok-contacts search "Ada"
grok-contacts show --id CONTACTID
grok-contacts gaps

grok-contacts create --first "Ada" --last "Lovelace" --phone "mobile:555-0100" --email "work:ada@example.com" --group "Engineers"
grok-contacts update --id CONTACTID --org "Analytical Engines" --add-phone "work:555-0199"
grok-contacts add-to-group --id CONTACTID --group "Engineers"
grok-contacts remove-from-group --id CONTACTID --group "Engineers"
grok-contacts delete --id CONTACTID --force
grok-contacts create-group "Engineers"
grok-contacts delete-group "Engineers" --force
```

Add `--json` on any command. `search` and `groups` do not print phone numbers, emails, or street addresses. `show` does, for one card. Deletes need `--force`. Deleting a group with more than 30 members also needs `--allow-large`. Deleting a group does not delete the people in it.

The first Contacts command needs Automation permission for the calling app to control Contacts (System Settings → Privacy & Security → Automation). Error -1743 means that grant is missing. A dialog that says “Grok Bot” wants access to control “Contacts” is that prompt: click Allow.
