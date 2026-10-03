# Capability gaps (honest)

Updated 2026-10-03 about 1:40 PM CT. Measured doctors for Notes, Contacts, and Messages are the earlier same-day snapshot in AUDIT.md. Calendar, Reminders, and Mail doctors were not re-run. See SCOPE_AUDIT.md for the full Mac + iOS 27 map.

## Shipped limits

- Notes 0.2.1: no pin/lock/drawings/scans/tables/audio; checklist checked-state is flaky; tags are hashtags in the cache (`tags --folder` does not start a live search)
- Contacts 0.1.1: no phone or email search (`search --field phone|email` exits `unsupported_field` and does not call Contacts); no merge, photos, or vCard
- Messages 0.2.1: plain-text send only; `--to` is 1:1; groups need `--chat-guid`; `attachments` is metadata for one chat (no absolute path, no file open, no send)
- Calendar 0.1.2: Automation Allow still required; `show` can return recurrence plus attendee and alarm counts once Allow lands; create/update/delete have offline `--dry-run`
- Reminders 0.1.2: Automation Allow still required; `add --dry-run` validates the due format; `show` also reads remind-me date and all-day when Allow lands
- Mail 0.1.2: no send; draft `--dry-run` checks subject and `@`; doctor not retried
- Shortcuts 0.1.1: `run` needs `--force`; `--dry-run` only checks that the name is installed
- iCloud 0.1.1: CloudDocs only; `summary` counts local bytes and evicted files; no download
- Spotlight 0.1.0: paths only, Documents/Desktop by default; Keychains, Messages, Mail, HomeKit, Passes, Safari, Cookies refused

## Deliberately not built

Focus database, Notification Center, Safari bookmarks, Maps, Find My, Screen Time, Continuity Camera, AirDrop, Freeform, Journal, Photos, Voice Memos, Weather store, Clock alarms, System Settings toggles, widgets, Lock Screen, Control Center, Stage Manager, Handoff, Universal Clipboard, iCloud Keychain, Wallet, HomeKit.

## When Phillip is back

One Allow click each for Calendar, Reminders, and Mail, then one doctor each. Details in SCOPE_AUDIT.md.
