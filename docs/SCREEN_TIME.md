# Screen Time

Screen Time is not an Apple Desk CLI. There is no `grok-screentime` command. Do not read Screen Time databases or usage samples.

Checked only whether the app bundle has `OSAScriptingDefinition`. No Screen Time database and no usage sample was read.

`/System/Applications/Screen Time.app` is not present.

The bundle is `/System/Library/CoreServices/Screen Time.app`. `Info.plist` has no `OSAScriptingDefinition`. The app does not publish an AppleScript dictionary, so it is not scriptable from this repo.

A dry-run that only checks the path and that key:

```bash
test -d "/System/Applications/Screen Time.app"
plutil -extract OSAScriptingDefinition raw -o - "/System/Library/CoreServices/Screen Time.app/Contents/Info.plist"
```

Both exit 1. The first exits 1 because that path is absent. The second exits 1 because the key is absent.
