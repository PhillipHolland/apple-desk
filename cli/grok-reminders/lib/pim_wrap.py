#!/usr/bin/env python3
"""Shell out to apple-pim reminder-cli. Not a second EventKit backend.

MIT omarshahine/apple-pim. This file does not vendor that source.
Doctor is auth-status plus, only when already authorized, a list count.
It does not walk reminder items. Missing binary falls through (exit 86).
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys

FALLBACK = 86
SKIP_TITLES = {"scheduled reminders", "siri suggestions", "birthdays"}
TCC_MAP = {
    "authorized": "authorized",
    "writeonly": "write-only",
    "denied": "denied",
    "restricted": "restricted",
    "notdetermined": "not-determined",
}
PRIORITY = {"high": "1", "medium": "5", "low": "9", "none": "0"}


def binary():
    env = os.environ.get("GROK_REMINDER_CLI")
    if env:
        return env
    found = shutil.which("reminder-cli")
    if found:
        return found
    home = os.path.expanduser("~/.local/bin/reminder-cli")
    if os.path.isfile(home) and os.access(home, os.X_OK):
        return home
    return None


def run(bin_path, args, timeout=25):
    return subprocess.run([bin_path, *args], capture_output=True, text=True, timeout=timeout)


def parse(argv):
    cmd = None
    pos = []
    flags = {}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--":
            pos.extend(argv[i + 1 :])
            break
        if a.startswith("--"):
            key = a[2:]
            if i + 1 < len(argv) and not argv[i + 1].startswith("--"):
                flags.setdefault(key, []).append(argv[i + 1])
                i += 2
            else:
                flags.setdefault(key, []).append(True)
                i += 1
        else:
            if cmd is None:
                cmd = a
            else:
                pos.append(a)
            i += 1
    return cmd, pos, flags


def one(flags, key):
    vals = flags.get(key) or []
    return None if not vals else vals[-1]


def emit(payload, as_json):
    if as_json:
        print(json.dumps(payload))
        return
    print("grok-reminders  backend: reminder-cli")
    print(f"tcc: {payload.get('tcc')}")
    if payload.get("binary"):
        print(f"binary: {payload['binary']}")
    if payload.get("lists") is not None:
        print(f"lists: {payload['lists']}")
    if payload.get("skipped"):
        print(f"skipped: {', '.join(payload['skipped'])}")
    if payload.get("message"):
        print(payload["message"])
    if payload.get("ok"):
        print("ok")


def doctor(bin_path, as_json):
    proc = run(bin_path, ["auth-status"], timeout=8)
    tcc = "unavailable"
    try:
        raw = json.loads(proc.stdout).get("authorization", "")
        tcc = TCC_MAP.get(str(raw).lower(), "unavailable")
    except json.JSONDecodeError:
        tcc = "unavailable"
    payload = {
        "ok": tcc == "authorized" and proc.returncode == 0,
        "tool": "grok-reminders",
        "backend": "reminder-cli",
        "binary": os.path.basename(bin_path),
        "tcc": tcc,
        "lists": None,
    }
    if tcc != "authorized":
        payload["message"] = proc.stderr.strip() or "Reminders full access is not authorized. auth-status does not prompt."
        emit(payload, as_json)
        return 0 if tcc in {"denied", "restricted", "not-determined", "write-only"} else 1
    proc = run(bin_path, ["lists"], timeout=12)
    titles = []
    try:
        data = json.loads(proc.stdout)
        for item in data.get("lists") or []:
            titles.append(item.get("title") or "")
    except json.JSONDecodeError:
        payload["ok"] = False
        payload["message"] = proc.stderr.strip() or "reminder-cli lists did not return JSON"
        emit(payload, as_json)
        return 1
    skipped = [t for t in titles if t.strip().lower() in SKIP_TITLES]
    payload["lists"] = len(titles) - len(skipped)
    payload["skipped"] = skipped
    payload["ok"] = proc.returncode == 0
    emit(payload, as_json)
    return 0 if payload["ok"] else 1


def mapped(cmd, pos, flags):
    # The external backend has no dry-run contract. Never turn a preview into
    # complete/delete merely by dropping the caller's flag.
    if flags.get("dry-run"):
        return None
    if cmd == "lists" and not flags.get("counts"):
        return ["lists"]
    if cmd == "today":
        args = ["items", "--filter", "today"]
        if one(flags, "list"):
            args += ["--list", one(flags, "list")]
        return args
    if cmd == "upcoming":
        args = ["items", "--filter", "upcoming"]
        if one(flags, "list"):
            args += ["--list", one(flags, "list")]
        return args
    if cmd == "search":
        query = pos[0] if pos else None
        if not query:
            return None
        args = ["search", query]
        if one(flags, "list"):
            args += ["--list", one(flags, "list")]
        if flags.get("include-completed"):
            args.append("--completed")
        return args
    if cmd == "show":
        if not one(flags, "id"):
            return None
        return ["get", "--id", one(flags, "id")]
    if cmd == "add":
        if flags.get("dry-run"):
            return None
        args = ["create", "--title", one(flags, "title") or ""]
        if one(flags, "list"):
            args += ["--list", one(flags, "list")]
        if one(flags, "due"):
            args += ["--due", one(flags, "due")]
        if one(flags, "notes"):
            args += ["--notes", one(flags, "notes")]
        pri = one(flags, "priority")
        if pri:
            args += ["--priority", PRIORITY.get(pri, "0")]
        return args
    if cmd == "done":
        if not one(flags, "id"):
            return None
        return ["complete", "--id", one(flags, "id")]
    if cmd == "delete":
        return ["delete", "--id", one(flags, "id") or ""]
    return None


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in {"-h", "--help", "--version", "gaps"}:
        raise SystemExit(FALLBACK)
    if any(arg.startswith("--dry-run=") for arg in argv):
        print(json.dumps({"ok": False, "error": "invalid_option", "message": "--dry-run does not take a value. No backend was called."}))
        raise SystemExit(2)
    cmd, pos, flags = parse(argv)
    if flags.get("dry-run") and cmd in {"add", "done", "delete"}:
        field = "title" if cmd == "add" else "id"
        target = one(flags, field)
        if not isinstance(target, str) or not target.strip():
            print(json.dumps({"ok": False, "error": "missing_" + field, "message": "Pass --" + field + ". No backend was called."}))
            raise SystemExit(2)
        preview_flags = {key: value for key, value in flags.items() if key != "dry-run"}
        payload = {"ok": True, "tool": "grok-reminders", "dryRun": True, "action": cmd,
                   "backendCalled": False, "plannedArguments": mapped(cmd, pos, preview_flags),
                   "message": "Dry-run only. No Reminders backend was called."}
        if flags.get("json"):
            print(json.dumps(payload))
        else:
            print(payload["message"])
        raise SystemExit(0)
    if cmd in {None, "gaps"} or flags.get("counts") or flags.get("live"):
        raise SystemExit(FALLBACK)
    bin_path = binary()
    as_json = bool(flags.get("json"))
    if not bin_path:
        raise SystemExit(FALLBACK)
    if cmd == "doctor":
        raise SystemExit(doctor(bin_path, as_json))
    if cmd == "delete" and not flags.get("force"):
        msg = "delete refuses without --force. reminder-cli was not called."
        if as_json:
            print(json.dumps({"ok": False, "error": "needs_force", "message": msg}))
        else:
            print(msg, file=sys.stderr)
        raise SystemExit(2)
    args = mapped(cmd, pos, flags)
    if not args:
        raise SystemExit(FALLBACK)
    proc = subprocess.run([bin_path, *args])
    raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()
