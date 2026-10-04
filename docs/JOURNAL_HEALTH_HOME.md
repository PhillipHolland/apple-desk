# Journal, Health, and Home

None of these three is an Apple Desk CLI. Journal and Home have no AppleScript dictionary. There is no Health app on this Mac. Do not invent a `grok-journal`, `grok-health`, or `grok-home` command, and do not run their App Intents from this repo. An intent that searches entries, lists accessories, or toggles a device is a live read or a live control, not a dry-run.

Checked from the app bundles and the Mac SDK only. No journal entry, health sample, or home accessory was read.

## Journal

`/System/Applications/Journal.app` is installed. Bundle id `com.apple.journal`. `Info.plist` has no `OSAScriptingDefinition` and no `NSAppleScriptEnabled`. There is no scripting-definition file in the bundle.

The app does ship App Intents metadata. Discoverable names include `CreateEntryIntent`, `CreateEntryAudioIntent`, and `SearchEntriesIntent`. Those can create or search entries. This repo does not call them.

Privacy strings on the app include camera, microphone, photo library, location, Face ID, Apple Music, and `NSHealthShareUsageDescription` / `NSHealthUpdateUsageDescription`. Those last two say journal data can be shared with Apple Health. They are not a Health sample query.

A dry-run that only checks the dictionary, and does not launch the app or read entries:

```bash
plutil -extract OSAScriptingDefinition raw -o - /System/Applications/Journal.app/Contents/Info.plist
plutil -extract NSAppleScriptEnabled raw -o - /System/Applications/Journal.app/Contents/Info.plist
```

Both exit 1 because the keys are absent.

## Health

`/System/Applications/Health.app` is not installed. `open` cannot find an application named Health. There is no Health command-line tool.

`/System/Library/Frameworks/HealthKit.framework` is present, and the Mac SDK has HealthKit headers. `isHealthDataAvailable` is the documented capability check. It does not return samples. This repo does not call it, and it does not run a sample, workout, or medication query.

A dry-run that only checks the app is missing:

```bash
test -d /System/Applications/Health.app
```

That exits 1 when the app is absent.

## Home

`/System/Applications/Home.app` is installed. `Info.plist` has no `OSAScriptingDefinition` and no `NSAppleScriptEnabled`. The keys that are present are location strings and a regulatory privacy disclosure. There is no `NSHomeKitUsageDescription` in that plist.

`/System/Library/Frameworks/HomeKit.framework` exists as a plugins bundle. The Mac SDK used for this check has no HomeKit headers.

Home widget metadata includes discoverable `ToggleIntent` and queries named `AccessoryAndSceneQuery` and `HomeEntityQuery`. Running those would list or control accessories. This repo does not call them.

An unsigned helper that asked for the Home TCC service `kTCCServiceWillow` got preflight 2 and then aborted. It did not return homes, rooms, or accessories. Do not repeat that request.

A dry-run that only checks the dictionary:

```bash
plutil -extract OSAScriptingDefinition raw -o - /System/Applications/Home.app/Contents/Info.plist
plutil -extract NSAppleScriptEnabled raw -o - /System/Applications/Home.app/Contents/Info.plist
```

Both exit 1 because the keys are absent.
