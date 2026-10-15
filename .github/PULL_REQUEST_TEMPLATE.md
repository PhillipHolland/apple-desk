## Summary

<!-- What changed and why. -->

## Test plan

- [ ] `./scripts/test.sh` (offline)
- [ ] If you touched a live Apple-app path, say what you could not verify without a Mac

## Safety

- [ ] No secrets, phone numbers, emails, chat text, or home-directory paths
- [ ] Send / consent gates are unchanged (`--force --confirm`, 1:1 `--to`, deletes need `--force`)
- [ ] `chat.db` stays read-only
