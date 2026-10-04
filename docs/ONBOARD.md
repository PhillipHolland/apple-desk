# Permission setup and diagnostics

Start from the terminal or agent process that will actually run Apple Desk on this Mac:

```sh
apple-desk doctor
apple-desk permissions request --mail
apple-desk permissions request --calendar
apple-desk doctor
```

Each request is explicit and can open a macOS permission dialog. A normal doctor call does not request access. Its successful execution means the diagnostic completed; inspect the nested authorization report to see whether the service is available.

## Calendar

Calendar uses a bundled native EventKit helper and requires **Full Access** to read, list, or verify changes. Write Only does not permit listing events. The helper explicitly requests full access using the macOS 14 API and includes the matching usage description.

If access is denied, look under **System Settings → Privacy & Security → Calendars** for the process identified by macOS. It may be associated with the launching terminal or host process rather than the CLI command name. Do not assume there must be an entry named `macdesk` or a separate “Full Access” toggle. The explicit request is what asks macOS for the correct level. Recheck the tool's actual status afterward.

If no request can appear or the state remains write-only, keep the returned status/error and identify the actual calling host. Do not repeatedly reset permissions or toggle unrelated apps. A moved or rebuilt development helper can need a fresh grant. Calendar.app does not need to be automated for EventKit reads.

## Mail

Mail uses Mail.app Automation. Status checks neither launch Mail nor read messages. The explicit request may launch Mail and ask to automate it. If Mail is not running, ordinary commands report that state; the explicit `--launch` option allows launch when needed. Permission to Calendar does not authorize Mail, and Mail permission does not authorize sending.

A timeout is not proof of denied permission. Slow Mail calls return a timeout; searches retain the latest completed checkpoint. Resume a non-null next cursor with unchanged scope and filters. If mailbox edits invalidate its anchors, restart discovery as instructed by the stale-cursor error.

## Other app tools and indexes

`apple-desk desk onboard --guided` is a passive inventory. It does not automatically prompt every app or build personal-data indexes. Some legacy app commands need their own Automation permission. Messages history requires Full Disk Access for the actual terminal/host. Only enable access for tools you intend to use.

Index collection is a separate, explicit action:

```sh
apple-desk desk reindex --only calendar
apple-desk desk status
```

Calendar indexes include their collection window and freshness. Incomplete, stale, or out-of-window data must not be treated as an exhaustive answer. Live Calendar commands always use EventKit.

An optional message signature can be set with `apple-desk desk signature --set "your chosen text"`; it is not automatically appended by send commands. Never infer permission to send from the presence of a signature.

The retained Messages reaction wrapper has separate UI limits: `imsg react` may need Messages in front and targets the last or selected message, not a stable GUID. Locked-screen tapbacks remain unsupported. Apple Desk does not disable SIP or inject IMCore to bypass that limitation. Legacy app exit codes differ from the new Mail/Calendar schema; inspect each command's error rather than applying a universal permission rule to a number.
