# Ethics

- Credit public prior art in `PRIOR_ART.md`. Do not vendor RemCTL, NotesCTL, imsg, apple-tools, or apple-pim source into this repo.
- Do not disable SIP. Do not use private IMCore.
- Do not use Viticci product names as Apple Desk CLI names.
- Writes stay a dry-run unless `--force`. That covers Notes create/edit/append, calendar create/update, reminders add and done, and contacts create/update. Deletes stay on `--force`.
- Calendar and reminders honor `--dry-run` even when a vendor CLI is installed. A dry-run does not call that vendor CLI.
- Messages send needs a draft, an explicit yes, and `grok-messages send --force --confirm TOKEN`. `--force` alone does not send. Do not send Mail unless the user named the recipient and the text.
- `grok-desk reindex` and onboard stay metadata-only for Messages and Notes unless `--index-bodies`.
- Caches stay local under `~/.cache/grok-*` (0700 / 0600). Nothing is uploaded by these CLIs.
- Ship portable behavior for any Mac. Host-only verification notes are not product defaults.
- Health and Journal are parked. There is no Mac Health app. Journal is not reachable from the shell or AppleScript. Home has no CLI; see `docs/HOME.md`.
