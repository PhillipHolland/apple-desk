# grok-spotlight

Scoped wrapper around `/usr/bin/mdfind`. Returns paths, not file contents.

```bash
grok-spotlight doctor
grok-spotlight search "budget" --onlyin ~/Documents --limit 20 --json
grok-spotlight search "report" --name --onlyin ~/Desktop
grok-spotlight gaps --json
```

Default scope, if you omit `--onlyin`, is `~/Documents` and `~/Desktop` only.
Paths under Keychains, Messages, Mail, HomeKit, Passwords, Safari, or Cookies are refused.
