#!/usr/bin/env python3
"""grok-shortcuts: list and run macOS Shortcuts. run does nothing without --force."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys

VERSION = "0.1.0"

GAPS = [
    "This wraps /usr/bin/shortcuts. It can list shortcuts and folders, and run one shortcut by name. It cannot create, edit, sign, or delete a shortcut.",
    "view opens Shortcuts.app on a shortcut. This CLI does not call view.",
    "run is not a dry read. A shortcut can send messages, place calls, toggle Home, write files, or anything else it was built to do. The wrapper does not inspect the shortcut graph, so it cannot tell a safe shortcut from a destructive one.",
    "run does nothing unless --force is present. Agents must not pass --force unless the user named that shortcut and accepted its side effects.",
    "There is no input builder beyond --input-path, and no way to pass a text stdin payload. Output goes to --output-path when the shortcut produces a file.",
    "Folder listing is names only. Identifiers need --show-identifiers and are opaque.",
    "Shortcuts iCloud sync can lag. A shortcut that exists on another device may be missing here until Shortcuts.app has downloaded it.",
    "No Voice Memos, dictation, or audio capture. Do not bolt those on.",
]


def die(code, error, message, as_json):
    if as_json:
        print(json.dumps({
            "ok": False,
            "tool": "grok-shortcuts",
            "version": VERSION,
            "error": error,
            "code": code,
            "message": message,
        }))
    else:
        print(f"grok-shortcuts: {error}", file=sys.stderr)
        if message:
            print(message, file=sys.stderr)
    raise SystemExit(code)


def run_shortcuts(args, timeout):
    proc = subprocess.run(["shortcuts", *args], capture_output=True, text=True, timeout=timeout)
    return proc


def emit(data, as_json, text_fn):
    if not data.get("ok", False):
        code = 2 if data.get("error") in {"needs_force", "missing_name", "bad_request"} else 1
        if as_json:
            data.setdefault("tool", "grok-shortcuts")
            data.setdefault("version", VERSION)
            print(json.dumps(data))
        else:
            print(f"grok-shortcuts: {data.get('error')}: {data.get('message', '')}", file=sys.stderr)
        raise SystemExit(code)
    if as_json:
        data.setdefault("tool", "grok-shortcuts")
        data.setdefault("version", VERSION)
        print(json.dumps(data))
    else:
        text_fn(data)


def _lines(proc):
    if proc.returncode != 0:
        blob = (proc.stderr or proc.stdout or "shortcuts failed").strip()
        return None, blob
    lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    return lines, None


def cmd_doctor(args):
    as_json = args.json
    try:
        proc = run_shortcuts(["list"], 30)
    except FileNotFoundError:
        die(1, "missing_cli", " /usr/bin/shortcuts is not on this Mac.", as_json)
    except subprocess.TimeoutExpired:
        die(4, "timeout", "shortcuts list timed out. Nothing was run.", as_json)
    lines, err = _lines(proc)
    if err is not None:
        die(1, "shortcuts_error", err, as_json)
    data = {
        "ok": True,
        "backend": "shortcuts-cli",
        "runRequiresForce": True,
        "count": len(lines),
    }

    def text(d):
        print(f"grok-shortcuts {VERSION}  ok")
        print(f"shortcuts: {d['count']}")
        print("run: refused without --force (no shortcut was run)")

    emit(data, as_json, text)


def cmd_list(args):
    as_json = args.json
    cmd = ["list"]
    if args.folders:
        cmd.append("--folders")
    if args.show_identifiers:
        cmd.append("--show-identifiers")
    if args.folder:
        cmd.extend(["--folder-name", args.folder])
    try:
        proc = run_shortcuts(cmd, 30)
    except subprocess.TimeoutExpired:
        die(4, "timeout", "shortcuts list timed out.", as_json)
    lines, err = _lines(proc)
    if err is not None:
        die(1, "shortcuts_error", err, as_json)
    data = {"ok": True, "folders": bool(args.folders), "count": len(lines), "names": lines}

    def text(d):
        kind = "folders" if d["folders"] else "shortcuts"
        print(f"{d['count']} {kind}")
        for name in d["names"]:
            print(name)

    emit(data, as_json, text)


def cmd_run(args):
    as_json = args.json
    name = (args.name or "").strip()
    if not name:
        die(2, "missing_name", "Pass the shortcut name. Nothing was run.", as_json)
    if not args.force:
        die(
            2,
            "needs_force",
            f"Refusing to run {name!r} without --force. A shortcut can message, call, change Home, or write files. Nothing was run.",
            as_json,
        )
    cmd = ["run", name]
    for path in args.input_path or []:
        cmd.extend(["--input-path", path])
    if args.output_path:
        cmd.extend(["--output-path", args.output_path])
    if args.output_type:
        cmd.extend(["--output-type", args.output_type])
    try:
        proc = run_shortcuts(cmd, args.timeout)
    except subprocess.TimeoutExpired:
        die(4, "timeout", f"shortcuts run timed out after {args.timeout}s.", as_json)
    if proc.returncode != 0:
        blob = (proc.stderr or proc.stdout or "shortcuts run failed").strip()
        die(1, "shortcuts_error", blob, as_json)
    data = {
        "ok": True,
        "ran": True,
        "name": name,
        "stdout": (proc.stdout or "")[:4000],
    }

    def text(d):
        print(f"ran {d['name']}")
        if d["stdout"].strip():
            print(d["stdout"].rstrip())

    emit(data, as_json, text)


def cmd_gaps(_args):
    print("grok-shortcuts gaps")
    for item in GAPS:
        print(f"- {item}")


def build_parser():
    parser = argparse.ArgumentParser(prog="grok-shortcuts", description="List and run macOS Shortcuts")
    parser.add_argument("--version", action="version", version=f"grok-shortcuts {VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_json(p):
        p.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor")
    add_json(doctor)
    doctor.set_defaults(func=cmd_doctor)

    listing = sub.add_parser("list")
    add_json(listing)
    listing.add_argument("--folders", action="store_true")
    listing.add_argument("--show-identifiers", action="store_true")
    listing.add_argument("--folder")
    listing.set_defaults(func=cmd_list)

    run = sub.add_parser("run")
    add_json(run)
    run.add_argument("name")
    run.add_argument("--force", action="store_true")
    run.add_argument("--input-path", action="append")
    run.add_argument("--output-path")
    run.add_argument("--output-type")
    run.add_argument("--timeout", type=int, default=60)
    run.set_defaults(func=cmd_run)

    gaps = sub.add_parser("gaps")
    gaps.set_defaults(func=cmd_gaps)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    timeout = getattr(args, "timeout", None)
    if isinstance(timeout, int) and not 1 <= timeout <= 300:
        die(2, "bad_request", "--timeout must be 1 through 300 seconds.", getattr(args, "json", False))
    try:
        args.func(args)
    except BrokenPipeError:
        raise SystemExit(0)


if __name__ == "__main__":
    main()
