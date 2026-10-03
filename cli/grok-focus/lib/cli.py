#!/usr/bin/env python3
"""grok-focus: best-effort Focus status from the local Do Not Disturb database.

Does not write that database and does not enable Focus unless set --force
is given a shortcut the user already has.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = "0.1.0"
TOOL = "grok-focus"
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
NOTE = (
    "Best-effort on macOS 27. There is no supported Focus status API. "
    "Status is inferred from ~/Library/DoNotDisturb/DB on this Mac only. "
    "No storeAssertionRecords list usually means Focus is off here. "
    "Another signed-in device can still be in a different Focus. The file can lag."
)

GAPS = [
    "Status is best-effort on macOS 27. It reads ModeConfigurations.json and Assertions.json. It does not call System Settings and it does not prompt.",
    "A missing storeAssertionRecords list is treated as Focus off on this Mac. That can be wrong if the database has not flushed, or if Focus is active only on another device.",
    "Configured mode names come from ModeConfigurations.json. Per-app allow lists in ModeConfigurationsSecure.json are not read.",
    "set without --force does nothing. set --dry-run does nothing even with --force.",
    "There is no built-in writer. set --force still refuses unless --shortcut names a shortcut already installed in Shortcuts. The Do Not Disturb database is never written.",
    "Running that shortcut can do whatever the shortcut does, not only change Focus. grok-focus cannot see the shortcut graph.",
    "Sleep, Driving, and personal Focus modes are not distinguished beyond the name and identifier stored on this Mac.",
    "Notification Center, Focus filters, and Share Across Devices are not visible here.",
]


def die(code, error, message, as_json):
    payload = {
        "ok": False,
        "tool": TOOL,
        "version": VERSION,
        "error": error,
        "code": code,
        "message": message,
    }
    if as_json:
        print(json.dumps(payload))
    else:
        print("%s: %s" % (TOOL, error), file=sys.stderr)
        if message:
            print(message, file=sys.stderr)
    raise SystemExit(code)


def emit(data, as_json, text_fn):
    if not data.get("ok", False):
        code = data.get("code", 1)
        if as_json:
            data.setdefault("tool", TOOL)
            data.setdefault("version", VERSION)
            data.setdefault("code", code)
            print(json.dumps(data))
        else:
            print("%s: %s: %s" % (TOOL, data.get("error"), data.get("message", "")), file=sys.stderr)
        raise SystemExit(code)
    if as_json:
        data.setdefault("tool", TOOL)
        data.setdefault("version", VERSION)
        print(json.dumps(data))
    else:
        text_fn(data)


def db_dir():
    return Path.home() / "Library" / "DoNotDisturb" / "DB"


def read_json(path, as_json):
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        die(5, "unreadable", "Missing %s. Nothing was changed and System Settings was not opened." % path.name, as_json)
    except PermissionError:
        die(
            5,
            "needs_full_disk_access",
            "Cannot read %s. Full Disk Access may be required. System Settings was not opened." % path.name,
            as_json,
        )
    except OSError as exc:
        die(1, "unreadable", "Cannot read %s: %s" % (path.name, exc), as_json)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        die(1, "bad_database", "%s is not JSON (%s)." % (path.name, exc), as_json)
    if not isinstance(data, dict):
        die(1, "bad_database", "%s has an unexpected shape." % path.name, as_json)
    return data


def apple_iso(value):
    if not isinstance(value, (int, float)):
        return None
    try:
        return (APPLE_EPOCH + timedelta(seconds=float(value))).isoformat()
    except OverflowError:
        return None


def os_version():
    try:
        proc = subprocess.run(["sw_vers", "-productVersion"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() or None


def find_lists(obj, key, acc):
    if isinstance(obj, dict):
        value = obj.get(key)
        if isinstance(value, list):
            acc.extend(value)
        for child in obj.values():
            find_lists(child, key, acc)
    elif isinstance(obj, list):
        for child in obj:
            find_lists(child, key, acc)


def dig(obj, key):
    if isinstance(obj, dict):
        if key in obj and not isinstance(obj[key], (dict, list)):
            return obj[key]
        for child in obj.values():
            found = dig(child, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for child in obj:
            found = dig(child, key)
            if found is not None:
                return found
    return None


def load_modes(as_json):
    path = db_dir() / "ModeConfigurations.json"
    data = read_json(path, as_json)
    modes = []
    blob = data.get("data")
    raw = None
    if isinstance(blob, list) and blob and isinstance(blob[0], dict):
        raw = blob[0].get("modeConfigurations")
    if not isinstance(raw, dict):
        raw = {}
    for identifier, body in raw.items():
        if not isinstance(identifier, str) or not isinstance(body, dict):
            continue
        mode = body.get("mode") if isinstance(body.get("mode"), dict) else {}
        name = mode.get("name") if isinstance(mode.get("name"), str) else identifier
        modes.append({"identifier": identifier, "name": name})
    modes.sort(key=lambda item: (item["name"].lower(), item["identifier"]))
    return modes


def active_modes(as_json, catalog):
    path = db_dir() / "Assertions.json"
    data = read_json(path, as_json)
    records = []
    find_lists(data, "storeAssertionRecords", records)
    by_id = {item["identifier"]: item["name"] for item in catalog}
    active = []
    seen = set()
    for record in records:
        if not isinstance(record, dict):
            continue
        identifier = dig(record, "assertionDetailsModeIdentifier")
        if not isinstance(identifier, str) or not identifier:
            continue
        if identifier in seen:
            continue
        seen.add(identifier)
        started = dig(record, "assertionStartDateTimestamp")
        active.append(
            {
                "identifier": identifier,
                "name": by_id.get(identifier, identifier),
                "startedAt": apple_iso(started),
            }
        )
    return active


def cmd_doctor(args):
    as_json = args.json
    catalog = load_modes(as_json)
    active = active_modes(as_json, catalog)
    data = {
        "ok": True,
        "bestEffort": True,
        "os": os_version(),
        "backend": "DoNotDisturb/DB",
        "configuredModeCount": len(catalog),
        "active": bool(active),
        "activeCount": len(active),
        "writesDatabase": False,
        "note": NOTE,
    }

    def text(d):
        print("grok-focus %s  ok (best-effort)" % VERSION)
        print("os: %s" % (d.get("os") or "unknown"))
        print("configured modes: %s" % d["configuredModeCount"])
        print("active on this Mac: %s" % ("yes" if d["active"] else "no"))
        print(d["note"])

    emit(data, as_json, text)


def cmd_status(args):
    as_json = args.json
    catalog = load_modes(as_json)
    active = active_modes(as_json, catalog)
    data = {
        "ok": True,
        "bestEffort": True,
        "os": os_version(),
        "active": bool(active),
        "activeModes": active,
        "configuredModes": catalog,
        "source": "Library/DoNotDisturb/DB/Assertions.json",
        "note": NOTE,
    }

    def text(d):
        if d["activeModes"]:
            print("Focus on: " + ", ".join(item["name"] for item in d["activeModes"]))
        else:
            print("Focus off on this Mac (best-effort)")
        print("%s configured mode(s)" % len(d["configuredModes"]))
        for item in d["configuredModes"]:
            print("- %s" % item["name"])

    emit(data, as_json, text)


def resolve_mode(raw, catalog):
    needle = (raw or "").strip()
    if not needle:
        return None
    folded = needle.casefold()
    for item in catalog:
        if item["identifier"] == needle or item["name"].casefold() == folded:
            return item
    return None


def shortcut_installed(name):
    try:
        proc = subprocess.run(["/usr/bin/shortcuts", "list"], capture_output=True, text=True, timeout=20)
    except FileNotFoundError:
        return False, "missing_cli"
    except subprocess.TimeoutExpired:
        return False, "timeout"
    if proc.returncode != 0:
        return False, "shortcuts_error"
    names = {line.strip() for line in (proc.stdout or "").splitlines() if line.strip()}
    return (name in names), None


def cmd_set(args):
    as_json = args.json
    catalog = load_modes(as_json)
    mode = resolve_mode(args.mode, catalog)
    if mode is None:
        die(2, "unknown_mode", "No configured Focus named %r. Nothing was changed." % (args.mode or ""), as_json)
    shortcut = (args.shortcut or "").strip()
    if args.dry_run:
        installed = None
        if shortcut:
            installed, err = shortcut_installed(shortcut)
            if err == "timeout":
                die(4, "timeout", "shortcuts list timed out. The shortcut was not run.", as_json)
            if err == "missing_cli":
                die(1, "missing_cli", "/usr/bin/shortcuts is not on this Mac. Nothing was changed.", as_json)
            if err:
                die(1, "shortcuts_error", "Could not list shortcuts. Nothing was changed.", as_json)
        data = {
            "ok": True,
            "dryRun": True,
            "wouldChange": False,
            "mode": mode,
            "shortcut": shortcut or None,
            "shortcutInstalled": installed,
            "message": "Dry-run only. Focus was not changed.",
        }

        def text(d):
            print("dry-run: would not change Focus")
            print("mode: %s" % d["mode"]["name"])
            if d["shortcut"]:
                print("shortcut installed: %s" % ("yes" if d["shortcutInstalled"] else "no"))

        emit(data, as_json, text)
        return
    if not args.force:
        die(
            2,
            "needs_force",
            "Refusing to enable or change Focus without --force. Nothing was changed.",
            as_json,
        )
    if not shortcut:
        die(
            2,
            "needs_shortcut",
            "No built-in Focus setter. Pass --shortcut NAME of an existing shortcut. "
            "The Do Not Disturb database was not written.",
            as_json,
        )
    installed, err = shortcut_installed(shortcut)
    if err == "timeout":
        die(4, "timeout", "shortcuts list timed out. The shortcut was not run.", as_json)
    if err == "missing_cli":
        die(1, "missing_cli", "/usr/bin/shortcuts is not on this Mac. Nothing was changed.", as_json)
    if err:
        die(1, "shortcuts_error", "Could not list shortcuts. Nothing was changed.", as_json)
    if not installed:
        die(2, "unknown_shortcut", "Shortcut %r is not installed. Nothing was run." % shortcut, as_json)
    try:
        proc = subprocess.run(["/usr/bin/shortcuts", "run", shortcut], capture_output=True, text=True, timeout=25)
    except subprocess.TimeoutExpired:
        die(4, "timeout", "shortcuts run timed out. Focus may or may not have changed.", as_json)
    if proc.returncode != 0:
        message = (proc.stderr or proc.stdout or "shortcuts run failed").strip()
        die(1, "shortcuts_error", message, as_json)
    data = {
        "ok": True,
        "changed": True,
        "mode": mode,
        "shortcut": shortcut,
        "message": "Shortcut ran. Confirm with status. grok-focus did not write the Do Not Disturb database.",
    }

    def text(d):
        print("ran shortcut %s" % d["shortcut"])
        print(d["message"])

    emit(data, as_json, text)


def cmd_gaps(args):
    as_json = getattr(args, "json", False)
    data = {"ok": True, "tool": TOOL, "version": VERSION, "gaps": GAPS}
    if as_json:
        print(json.dumps(data))
        return
    print("grok-focus gaps")
    for item in GAPS:
        print("- %s" % item)


def build_parser():
    parser = argparse.ArgumentParser(prog=TOOL, description="Best-effort Focus status. Does not toggle Focus unless set --force --shortcut.")
    parser.add_argument("--version", action="version", version="%s %s" % (TOOL, VERSION))
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_json(p):
        p.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor")
    add_json(doctor)
    doctor.set_defaults(func=cmd_doctor)

    status = sub.add_parser("status")
    add_json(status)
    status.set_defaults(func=cmd_status)

    setter = sub.add_parser("set")
    add_json(setter)
    setter.add_argument("--mode", required=True, help="Configured Focus name or identifier.")
    setter.add_argument("--shortcut", help="Existing Shortcuts name to run. Required with --force.")
    setter.add_argument("--dry-run", action="store_true", help="Validate only. Never changes Focus.")
    setter.add_argument("--force", action="store_true", help="Allow running --shortcut. Still does not write the Focus database.")
    setter.set_defaults(func=cmd_set)

    gaps = sub.add_parser("gaps")
    add_json(gaps)
    gaps.set_defaults(func=cmd_gaps)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
