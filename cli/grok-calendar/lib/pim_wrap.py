#!/usr/bin/env python3
"""Shell out to apple-pim calendar-cli. Not a second EventKit backend.

MIT omarshahine/apple-pim. This file does not vendor that source.
Doctor is auth-status plus, only when already authorized, a calendar-name count.
It does not list events. Missing binary falls through to the in-house CLI (exit 86).
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


def binary():
    env = os.environ.get("GROK_CALENDAR_CLI")
    if env:
        return env
    found = shutil.which("calendar-cli")
    if found:
        return found
    home = os.path.expanduser("~/.local/bin/calendar-cli")
    if os.path.isfile(home) and os.access(home, os.X_OK):
        return home
    return None


def run(bin_path, args, timeout=25):
    proc = subprocess.run(
        [bin_path, *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


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


def wants_json(flags):
    return bool(flags.get("json"))


def emit(payload, as_json):
    if as_json:
        print(json.dumps(payload))
        return
    print(f"grok-calendar  backend: calendar-cli")
    print(f"tcc: {payload.get('tcc')}")
    if payload.get("binary"):
        print(f"binary: {payload['binary']}")
    if payload.get("calendars") is not None:
        print(f"calendars: {payload['calendars']}")
    if payload.get("skipped"):
        print(f"skipped: {', '.join(payload['skipped'])}")
    if payload.get("message"):
        print(payload["message"])
    if payload.get("ok"):
        print("ok")


def doctor(bin_path, as_json):
    code, out, err = run(bin_path, ["auth-status"], timeout=8)
    tcc = "unavailable"
    try:
        raw = json.loads(out).get("authorization", "")
        tcc = TCC_MAP.get(str(raw).lower(), "unavailable")
    except json.JSONDecodeError:
        tcc = "unavailable"
    payload = {
        "ok": tcc == "authorized" and code == 0,
        "tool": "grok-calendar",
        "backend": "calendar-cli",
        "binary": os.path.basename(bin_path),
        "tcc": tcc,
        "calendars": None,
    }
    if tcc != "authorized":
        payload["message"] = err.strip() or "Calendar full access is not authorized. auth-status does not prompt."
        emit(payload, as_json)
        return 0 if tcc in {"denied", "restricted", "not-determined", "write-only"} else 1
    code, out, err = run(bin_path, ["list"], timeout=12)
    titles = []
    try:
        data = json.loads(out)
        for cal in data.get("calendars") or []:
            titles.append(cal.get("title") or "")
    except json.JSONDecodeError:
        payload["ok"] = False
        payload["message"] = err.strip() or "calendar-cli list did not return JSON"
        emit(payload, as_json)
        return 1
    skipped = [t for t in titles if t.strip().lower() in SKIP_TITLES]
    payload["calendars"] = len(titles) - len(skipped)
    payload["skipped"] = skipped
    payload["ok"] = code == 0
    emit(payload, as_json)
    return 0 if payload["ok"] else 1


def mapped(cmd, pos, flags):
    if cmd == "calendars":
        return ["list"]
    if cmd == "list":
        args = ["events"]
        if one(flags, "today") is True or one(flags, "today"):
            args += ["--from", "today", "--to", "today"]
        else:
            if one(flags, "from"):
                args += ["--from", one(flags, "from")]
            if one(flags, "to"):
                args += ["--to", one(flags, "to")]
            elif one(flags, "days"):
                args += ["--to", f"+{one(flags, 'days')}d"]
        if one(flags, "calendar"):
            args += ["--calendar", one(flags, "calendar")]
        if one(flags, "limit"):
            args += ["--limit", str(one(flags, "limit"))]
        return args
    if cmd == "search":
        query = pos[0] if pos else one(flags, "query")
        if not query:
            return None
        args = ["search", query]
        if one(flags, "calendar"):
            args += ["--calendar", one(flags, "calendar")]
        if one(flags, "limit"):
            args += ["--limit", str(one(flags, "limit"))]
        return args
    if cmd == "show":
        uid = one(flags, "uid")
        if not uid:
            return None
        return ["get", "--id", uid]
    if cmd == "create":
        args = ["create", "--title", one(flags, "title") or "", "--start", one(flags, "start") or ""]
        for src, dst in (("end", "end"), ("calendar", "calendar"), ("location", "location"), ("notes", "notes")):
            if one(flags, src):
                args += [f"--{dst}", one(flags, src)]
        if flags.get("all-day"):
            args.append("--all-day")
        return args
    if cmd == "update":
        uid = one(flags, "uid")
        if not uid:
            return None
        args = ["update", "--id", uid]
        for src in ("title", "start", "end", "location", "notes"):
            if one(flags, src):
                args += [f"--{src}", one(flags, src)]
        return args
    if cmd == "delete":
        return ["delete", "--id", one(flags, "uid") or ""]
    return None


def main():
    argv = sys.argv[1:]
    if not argv or argv[0] in {"-h", "--help", "--version", "gaps"}:
        raise SystemExit(FALLBACK)
    cmd, pos, flags = parse(argv)
    if cmd in {None, "gaps"}:
        raise SystemExit(FALLBACK)
    # alarm stays on the in-house JXA path. Do not forward it to calendar-cli (EventKit).
    if cmd == "alarm":
        raise SystemExit(FALLBACK)
    bin_path = binary()
    as_json = wants_json(flags)
    if not bin_path:
        raise SystemExit(FALLBACK)
    if cmd == "doctor":
        raise SystemExit(doctor(bin_path, as_json))
    if cmd == "name-at":
        code, out, err = run(bin_path, ["list"], timeout=12)
        try:
            data = json.loads(out)
            cals = data.get("calendars") or []
        except json.JSONDecodeError:
            print(err or out, file=sys.stderr)
            raise SystemExit(1)
        idx = int(one(flags, "index") or -1)
        if idx < 0 or idx >= len(cals):
            print("grok-calendar: index out of range", file=sys.stderr)
            raise SystemExit(2)
        title = cals[idx].get("title") or ""
        if as_json:
            print(json.dumps({"ok": True, "index": idx, "title": title, "backend": "calendar-cli"}))
        else:
            print(title)
        raise SystemExit(0 if code == 0 else code)
    # --dry-run must not call calendar-cli. Exit 86 so the in-house CLI prints the dry-run.
    if cmd in {"create", "update", "delete"} and flags.get("dry-run"):
        raise SystemExit(FALLBACK)
    # create and update are dry-run unless --force. Fall through to the JXA dry-run.
    if cmd in {"create", "update"} and not flags.get("force"):
        raise SystemExit(FALLBACK)
    if cmd == "delete" and not flags.get("force"):
        msg = "delete refuses without --force. calendar-cli was not called."
        if as_json:
            print(json.dumps({"ok": False, "error": "needs_force", "message": msg}))
        else:
            print(msg, file=sys.stderr)
        raise SystemExit(2)
    args = mapped(cmd, pos, flags)
    if not args:
        raise SystemExit(FALLBACK)
    try:
        proc = subprocess.run([bin_path, *args])
    except subprocess.TimeoutExpired:
        print("grok-calendar: calendar-cli timed out", file=sys.stderr)
        raise SystemExit(1)
    raise SystemExit(proc.returncode)


if __name__ == "__main__":
    main()
