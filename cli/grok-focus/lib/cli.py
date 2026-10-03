#!/usr/bin/env python3
"""grok-focus: best-effort Focus status from the local Do Not Disturb database.

Portable for any user on any Mac. Discovers Focus modes from this Mac's
DoNotDisturb DB. Does not write that database. Does not enable Focus unless
set --force is given a shortcut the user already has.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = "0.1.1"
TOOL = "grok-focus"
APPLE_EPOCH = datetime(2001, 1, 1, tzinfo=timezone.utc)
READ_TIMEOUT_SEC = 8.0
SHORTCUTS_LIST_TIMEOUT = 15
SHORTCUTS_RUN_TIMEOUT = 25

GAPS = [
    "Status is best-effort. It reads ModeConfigurations.json and Assertions.json under ~/Library/DoNotDisturb/DB. It does not call System Settings and it does not prompt.",
    "A missing storeAssertionRecords list is treated as Focus off on this Mac. That can be wrong if the database has not flushed, or if Focus is active only on another device.",
    "Configured mode names are discovered from ModeConfigurations.json on this Mac. They are not hardcoded. Per-app allow lists in ModeConfigurationsSecure.json are not read.",
    "set without --force does nothing. set --dry-run does nothing even with --force.",
    "There is no built-in writer. set --force still refuses unless --shortcut names a shortcut already installed in Shortcuts. The Do Not Disturb database is never written.",
    "Running that shortcut can do whatever the shortcut does, not only change Focus. grok-focus cannot see the shortcut graph.",
    "Sleep, Driving, and personal Focus modes are not distinguished beyond the name and identifier stored on this Mac.",
    "Notification Center, Focus filters, and Share Across Devices policy details are not fully visible here. MeDeviceStatus is reported when present as a hint only.",
    "Optional cache under ~/.cache/grok-focus stores the last mode catalog keyed to ModeConfigurations.json mtime. Clear with cache-clear.",
]


def die(code, error, message, as_json, **extra):
    payload = {
        "ok": False,
        "tool": TOOL,
        "version": VERSION,
        "error": error,
        "code": code,
        "message": message,
    }
    payload.update(extra)
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


def cache_dir():
    return Path.home() / ".cache" / "grok-focus"


def ensure_cache_dir():
    path = cache_dir()
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def portable_note(os_ver):
    ver = os_ver or "this Mac"
    return (
        "Best-effort Focus status on macOS %s. There is no supported Focus status API. "
        "Status is inferred from ~/Library/DoNotDisturb/DB on this Mac only. "
        "No storeAssertionRecords list usually means Focus is off here. "
        "Another signed-in device can still be in a different Focus. The file can lag."
    ) % ver


def iso_mtime(path):
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone().isoformat()
    except OSError:
        return None


def apple_iso(value):
    if not isinstance(value, (int, float)):
        return None
    try:
        return (APPLE_EPOCH + timedelta(seconds=float(value))).isoformat()
    except OverflowError:
        return None


def os_version():
    try:
        proc = subprocess.run(
            ["sw_vers", "-productVersion"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if proc.returncode != 0:
        return None
    return (proc.stdout or "").strip() or None


def read_json_file(path, as_json, required=True):
    started = time.monotonic()
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        if not required:
            return None
        die(
            5,
            "unreadable",
            "Missing %s under ~/Library/DoNotDisturb/DB. "
            "On a fresh Mac, enable any Focus once in Control Center so the database appears. "
            "Nothing was changed and System Settings was not opened." % path.name,
            as_json,
            hint="Enable a Focus mode once, or check Full Disk Access if the folder exists but files are missing.",
            path=str(path),
        )
    except PermissionError:
        die(
            5,
            "needs_full_disk_access",
            "Cannot read %s. Full Disk Access may be required for this process. "
            "System Settings was not opened." % path.name,
            as_json,
            hint="Grant Full Disk Access to the terminal or automation host running grok-focus, then retry doctor.",
            path=str(path),
        )
    except OSError as exc:
        die(1, "unreadable", "Cannot read %s: %s" % (path.name, exc), as_json, path=str(path))
    if time.monotonic() - started > READ_TIMEOUT_SEC:
        die(4, "timeout", "Reading %s took too long. Nothing was changed." % path.name, as_json)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        die(1, "bad_database", "%s is not JSON (%s)." % (path.name, exc), as_json)
    if not isinstance(data, dict):
        die(1, "bad_database", "%s has an unexpected shape." % path.name, as_json)
    return data


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


def parse_modes(data):
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
        symbol = mode.get("symbolImageName") if isinstance(mode.get("symbolImageName"), str) else None
        row = {"identifier": identifier, "name": name}
        if symbol:
            row["symbol"] = symbol
        modes.append(row)
    modes.sort(key=lambda item: (item["name"].lower(), item["identifier"]))
    return modes


def modes_cache_path():
    return cache_dir() / "modes.json"


def load_modes(as_json, use_cache=True):
    path = db_dir() / "ModeConfigurations.json"
    mtime = None
    try:
        mtime = path.stat().st_mtime
    except OSError:
        mtime = None
    cache_path = modes_cache_path()
    if use_cache and mtime is not None and cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                isinstance(cached, dict)
                and cached.get("sourceMtime") == mtime
                and isinstance(cached.get("modes"), list)
            ):
                return cached["modes"], True
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    data = read_json_file(path, as_json, required=True)
    modes = parse_modes(data)
    if use_cache and mtime is not None:
        try:
            ensure_cache_dir()
            payload = {"sourceMtime": mtime, "modes": modes, "cachedAt": datetime.now().astimezone().isoformat()}
            cache_path.write_text(json.dumps(payload), encoding="utf-8")
            try:
                os.chmod(cache_path, 0o600)
            except OSError:
                pass
        except OSError:
            pass
    return modes, False


def active_modes(as_json, catalog):
    path = db_dir() / "Assertions.json"
    data = read_json_file(path, as_json, required=True)
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


def me_device_hint(as_json):
    path = db_dir() / "MeDeviceStatus.json"
    data = read_json_file(path, as_json, required=False)
    if not data:
        return None
    blob = data.get("data")
    if not isinstance(blob, list) or not blob or not isinstance(blob[0], dict):
        return None
    row = blob[0]
    out = {}
    if "meDeviceStatus" in row:
        out["statusCode"] = row.get("meDeviceStatus")
    name = row.get("meDeviceName")
    if isinstance(name, str) and name.strip():
        # Discovered from this Mac's DB; not hardcoded product data.
        out["deviceName"] = name.strip()
    return out or None


def db_presence():
    root = db_dir()
    files = {
        "modeConfigurations": (root / "ModeConfigurations.json").is_file(),
        "assertions": (root / "Assertions.json").is_file(),
        "meDeviceStatus": (root / "MeDeviceStatus.json").is_file(),
        "globalConfiguration": (root / "GlobalConfiguration.json").is_file(),
    }
    return {
        "dirExists": root.is_dir(),
        "path": "Library/DoNotDisturb/DB",
        "files": files,
        "modesMtime": iso_mtime(root / "ModeConfigurations.json"),
        "assertionsMtime": iso_mtime(root / "Assertions.json"),
    }


def doctor_hints(presence, active, me_device):
    hints = []
    if not presence["dirExists"]:
        hints.append(
            "DoNotDisturb/DB is missing. On a fresh Mac, turn on any Focus once from Control Center so macOS creates the database."
        )
    else:
        missing = [name for name, ok in presence["files"].items() if not ok and name in ("modeConfigurations", "assertions")]
        if missing:
            hints.append("Expected Focus database files are missing: %s." % ", ".join(missing))
    if not active:
        hints.append("No active Focus assertion on this Mac (best-effort). Another device may still be in Focus.")
    if me_device and me_device.get("deviceName"):
        hints.append("MeDeviceStatus is present; Focus can differ across signed-in devices.")
    hints.append("set requires --force and an existing Shortcuts name; the Focus database is never written by grok-focus.")
    hints.append("Cache (optional): ~/.cache/grok-focus — mode catalog only, invalidated by ModeConfigurations.json mtime.")
    return hints


def cmd_doctor(args):
    as_json = args.json
    os_ver = os_version()
    presence = db_presence()
    if not presence["dirExists"] or not presence["files"]["modeConfigurations"]:
        data = {
            "ok": False,
            "error": "unreadable",
            "code": 5,
            "message": "Focus database not ready on this Mac.",
            "os": os_ver,
            "backend": "DoNotDisturb/DB",
            "db": presence,
            "cacheDir": str(cache_dir()),
            "writesDatabase": False,
            "hints": doctor_hints(presence, [], None),
            "note": portable_note(os_ver),
        }
        emit(data, as_json, lambda d: None)
        return
    catalog, from_cache = load_modes(as_json, use_cache=True)
    active = active_modes(as_json, catalog) if presence["files"]["assertions"] else []
    me_device = me_device_hint(as_json) if presence["files"]["meDeviceStatus"] else None
    data = {
        "ok": True,
        "bestEffort": True,
        "os": os_ver,
        "backend": "DoNotDisturb/DB",
        "db": presence,
        "configuredModeCount": len(catalog),
        "configuredModes": [{"name": m["name"], "identifier": m["identifier"]} for m in catalog],
        "active": bool(active),
        "activeCount": len(active),
        "activeModes": active,
        "meDevice": me_device,
        "modesFromCache": from_cache,
        "cacheDir": str(cache_dir()),
        "writesDatabase": False,
        "setRequiresForce": True,
        "hints": doctor_hints(presence, active, me_device),
        "note": portable_note(os_ver),
    }

    def text(d):
        print("grok-focus %s  ok (best-effort)" % VERSION)
        print("os: %s" % (d.get("os") or "unknown"))
        print("db: ~/%s (%s)" % (d["db"]["path"], "present" if d["db"]["dirExists"] else "missing"))
        print("configured modes: %s" % d["configuredModeCount"])
        for mode in d["configuredModes"]:
            print("  - %s" % mode["name"])
        if d["activeModes"]:
            print("active on this Mac: yes (%s)" % ", ".join(item["name"] for item in d["activeModes"]))
        else:
            print("active on this Mac: no")
        print("cache: %s (modes hit=%s)" % (d["cacheDir"], "yes" if d["modesFromCache"] else "no"))
        print("set: requires --force + existing --shortcut; database never written")
        for hint in d["hints"][:3]:
            print("hint: %s" % hint)
        print(d["note"])

    emit(data, as_json, text)


def cmd_status(args):
    as_json = args.json
    os_ver = os_version()
    presence = db_presence()
    catalog, from_cache = load_modes(as_json, use_cache=True)
    active = active_modes(as_json, catalog)
    lean = getattr(args, "lean", False)
    data = {
        "ok": True,
        "bestEffort": True,
        "os": os_ver,
        "active": bool(active),
        "activeModes": active,
        "configuredModeCount": len(catalog),
        "source": "Library/DoNotDisturb/DB/Assertions.json",
        "modesMtime": presence["modesMtime"],
        "assertionsMtime": presence["assertionsMtime"],
        "modesFromCache": from_cache,
        "cacheDir": str(cache_dir()),
        "note": portable_note(os_ver),
    }
    if not lean:
        data["configuredModes"] = catalog
    else:
        data["configuredModes"] = [{"name": m["name"], "identifier": m["identifier"]} for m in catalog]

    def text(d):
        if d["activeModes"]:
            print("Focus on: " + ", ".join(item["name"] for item in d["activeModes"]))
        else:
            print("Focus off on this Mac (best-effort)")
        print("%s configured mode(s)" % d["configuredModeCount"])
        for item in d["configuredModes"]:
            print("- %s" % item["name"])
        if d.get("assertionsMtime"):
            print("assertions mtime: %s" % d["assertionsMtime"])

    emit(data, as_json, text)


def cmd_modes(args):
    as_json = args.json
    catalog, from_cache = load_modes(as_json, use_cache=True)
    data = {
        "ok": True,
        "count": len(catalog),
        "modes": catalog,
        "fromCache": from_cache,
        "source": "Library/DoNotDisturb/DB/ModeConfigurations.json",
        "cacheDir": str(cache_dir()),
    }

    def text(d):
        print("%s configured Focus mode(s)" % d["count"])
        for item in d["modes"]:
            print("%s\t%s" % (item["name"], item["identifier"]))

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
        proc = subprocess.run(
            ["/usr/bin/shortcuts", "list"],
            capture_output=True,
            text=True,
            timeout=SHORTCUTS_LIST_TIMEOUT,
        )
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
    catalog, _from_cache = load_modes(as_json, use_cache=True)
    mode = resolve_mode(args.mode, catalog)
    if mode is None:
        known = ", ".join(item["name"] for item in catalog[:12])
        extra = (" Known on this Mac: %s." % known) if known else ""
        die(
            2,
            "unknown_mode",
            "No configured Focus named %r.%s Nothing was changed." % ((args.mode or ""), extra),
            as_json,
        )
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
        proc = subprocess.run(
            ["/usr/bin/shortcuts", "run", shortcut],
            capture_output=True,
            text=True,
            timeout=SHORTCUTS_RUN_TIMEOUT,
        )
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


def cmd_cache_clear(args):
    as_json = args.json
    path = modes_cache_path()
    removed = False
    if path.is_file():
        try:
            path.unlink()
            removed = True
        except OSError as exc:
            die(1, "cache_error", "Could not clear cache: %s" % exc, as_json)
    data = {"ok": True, "removed": removed, "cacheDir": str(cache_dir())}

    def text(d):
        print("cache cleared" if d["removed"] else "cache already empty")
        print(d["cacheDir"])

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
    parser = argparse.ArgumentParser(
        prog=TOOL,
        description="Best-effort Focus status for any Mac. Does not toggle Focus unless set --force --shortcut.",
    )
    parser.add_argument("--version", action="version", version="%s %s" % (TOOL, VERSION))
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_json(p):
        p.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor", help="Lean Focus readiness check. Discovers modes on this Mac.")
    add_json(doctor)
    doctor.set_defaults(func=cmd_doctor)

    status = sub.add_parser("status", help="Active Focus + configured modes (best-effort).")
    add_json(status)
    status.add_argument("--lean", action="store_true", help="Omit symbol fields; names and identifiers only.")
    status.set_defaults(func=cmd_status)

    modes = sub.add_parser("modes", help="List Focus modes discovered on this Mac.")
    add_json(modes)
    modes.set_defaults(func=cmd_modes)

    setter = sub.add_parser("set", help="Change Focus only with --force and an existing shortcut.")
    add_json(setter)
    setter.add_argument("--mode", required=True, help="Configured Focus name or identifier on this Mac.")
    setter.add_argument("--shortcut", help="Existing Shortcuts name to run. Required with --force.")
    setter.add_argument("--dry-run", action="store_true", help="Validate only. Never changes Focus.")
    setter.add_argument(
        "--force",
        action="store_true",
        help="Allow running --shortcut. Still does not write the Focus database.",
    )
    setter.set_defaults(func=cmd_set)

    cache_clear = sub.add_parser("cache-clear", help="Remove ~/.cache/grok-focus mode catalog.")
    add_json(cache_clear)
    cache_clear.set_defaults(func=cmd_cache_clear)

    gaps = sub.add_parser("gaps")
    add_json(gaps)
    gaps.set_defaults(func=cmd_gaps)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
