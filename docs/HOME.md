# Home

Home is not an Apple Desk CLI. There is no `grok-home` command. Do not invent one. Do not open Home.app. Do not list, read, or toggle accessories.

Checked only the Home.app bundle and `Info.plist` keys `OSAScriptingDefinition`, `NSAppleScriptEnabled`, and the privacy usage strings. No accessory was read. Shortcuts was not run.

## Bundle

`/System/Applications/Home.app` is installed. Bundle id `com.apple.Home`.

`Info.plist` has no `OSAScriptingDefinition` and no `NSAppleScriptEnabled`. A search of the bundle found no `.sdef` file. Home publishes no AppleScript dictionary, so this repo cannot script it.

Privacy usage strings in that plist:

- `NSLocationUsageDescription` — location for accessory automations, and so Siri can help control accessories.
- `NSLocationWhenInUseUsageDescription` — precise location to locate the home while setting up accessory automations.

`NSRegulatoryPrivacyDisclosure` version `1.0` is also present. It describes camera (setup codes and wallpaper photos), contacts (invites, plus names and photos of people in the home), location (precise address while setting up an accessory automation), microphone (intercom and other communications to cameras), and photos (wallpaper and familiar faces from cameras). There is no `NSHomeKitUsageDescription`.

A dry check of the scripting keys:

```bash
plutil -extract OSAScriptingDefinition raw -o - /System/Applications/Home.app/Contents/Info.plist
plutil -extract NSAppleScriptEnabled raw -o - /System/Applications/Home.app/Contents/Info.plist
```

Both exit 1 because the keys are absent.

## Shortcut the human already created

A Shortcut the human creates is the only way this repo documents reaching Home. The human creates that shortcut in Shortcuts. This repo does not create it, does not run it, and does not turn anything on or off.

`grok-shortcuts` 0.1.2 wraps `/usr/bin/shortcuts`. The flags named here are flags that command already has. `list` never runs a shortcut. `run` does nothing unless `--force` is present. `run "<shortcut>" --dry-run` checks whether that name is installed and does not run it. `<shortcut>` means the name the human already created. This repo does not ship one.

```bash
grok-shortcuts list
grok-shortcuts run "<shortcut>" --dry-run
```

`list` prints names. The dry-run prints `dry-run '<shortcut>' installed=True` or `installed=False`, then `(not run)`. Home is unchanged.

`create` cannot build a Home action. A shortcut it generates is a Comment action, plus Show Result when `--text` is set. `--from FILE.shortcut` signs a `.shortcut` file the human already has. `create` does nothing without `--force`. `create --dry-run` validates only and never signs or opens Shortcuts. This page does not call `create`.

`run` accepts `--force`. With `--force`, `grok-shortcuts` runs the named shortcut and does not inspect what that shortcut does. This page does not pass `--force`. Pass it only when the human has named that shortcut and accepted its effects.
