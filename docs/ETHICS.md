# Ethics

- Credit public prior art in `PRIOR_ART.md`. Do not vendor RemCTL, NotesCTL, imsg, apple-tools, or apple-pim source into this repo.
- Do not disable SIP. Do not use private IMCore.
- Do not use Viticci product names as Apple Desk CLI names.
- Writes stay gated (`--force` or the existing confirm gate). Agents must not send Messages or Mail unless the user named the recipient and the text.
- Caches stay local under `~/.cache/grok-*` (0700 / 0600). Nothing is uploaded by these CLIs.
- Ship portable behavior for any Mac. Host-only verification notes are not product defaults.
