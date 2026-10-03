#!/usr/bin/env python3
"""grok-spotlight: scoped Spotlight search via mdfind. Paths only, no file bytes."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

VERSION = "0.1.0"
TOOL = "grok-spotlight"

GAPS = [
    "This wraps /usr/bin/mdfind. It returns paths (and, with --count, a number). It does not read file bytes, open apps, or import metadata with mdimport.",
    "Without --onlyin, search is limited to ~/Documents and ~/Desktop. Pass --onlyin to add another folder. Whole-disk search is refused.",
    "Paths that resolve under Keychains, Messages, Mail, HomeKit, Passes, Safari, or Cookies are refused before mdfind runs.",
    "Spotlight's index can be stale or partial. A miss is not proof the file is gone. Evicted iCloud files may still be indexed.",
    "There is no write, no tag edit, and no 'open in Finder'. A query is a Spotlight predicate or, with --name, a filename substring.",
    "Mail, Messages, Contacts, and the password stores are not a search backend here even if Spotlight knows about them.",
]

BLOCKED_PARTS = {
    "keychains",
    "messages",
    "mail",
    "homekit",
    "passes",
    "safari",
    "cookies",
    "com.apple.homed",
}


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
        print(f"{TOOL}: {error}", file=sys.stderr)
        if message:
            print(message, file=sys.stderr)
    raise SystemExit(code)


def emit(data, as_json, text_fn):
    if not data.get("ok", False):
        code = 2 if data.get("error") in {"bad_request", "blocked_scope", "missing_query"} else 1
        if as_json:
            data.setdefault("tool", TOOL)
            data.setdefault("version", VERSION)
            data.setdefault("code", code)
            print(json.dumps(data))
        else:
            print(f"{TOOL}: {data.get('error')}: {data.get('message', '')}", file=sys.stderr)
        raise SystemExit(code)
    if as_json:
        data.setdefault("tool", TOOL)
        data.setdefault("version", VERSION)
        print(json.dumps(data))
    else:
        text_fn(data)


def default_roots():
    home = Path.home()
    roots = []
    for name in ("Documents", "Desktop"):
        path = home / name
        if path.is_dir():
            roots.append(path)
    return roots


def blocked(path: Path) -> bool:
    parts = {part.casefold() for part in path.parts}
    if parts & BLOCKED_PARTS:
        return True
    blob = str(path).casefold()
    if "library/group containers" in blob and "password" in blob:
        return True
    return False


def resolve_scope(raw, as_json):
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        resolved = path.resolve()
    except OSError as exc:
        die(2, "bad_request", f"Cannot resolve {raw}: {exc}", as_json)
    if not resolved.exists() or not resolved.is_dir():
        die(2, "bad_request", f"{resolved} is not a folder.", as_json)
    if blocked(resolved):
        die(2, "blocked_scope", f"Refusing to search {resolved}. That area is out of scope.", as_json)
    return resolved


def run_mdfind(args, timeout):
    return subprocess.run(["mdfind", *args], capture_output=True, text=True, timeout=timeout)


def cmd_doctor(args):
    as_json = args.json
    try:
        proc = run_mdfind(["-onlyin", "/System/Library/CoreServices", "-count", "Finder"], 15)
    except FileNotFoundError:
        die(1, "missing_cli", "/usr/bin/mdfind is not on this Mac.", as_json)
    except subprocess.TimeoutExpired:
        die(4, "timeout", "mdfind timed out during doctor. Nothing was opened.", as_json)
    if proc.returncode != 0:
        die(1, "spotlight_error", (proc.stderr or proc.stdout or "mdfind failed").strip(), as_json)
    data = {
        "ok": True,
        "backend": "mdfind",
        "readsFileBytes": False,
        "defaultScope": [str(p) for p in default_roots()],
    }

    def text(d):
        print(f"grok-spotlight {VERSION}  ok")
        print("backend: mdfind (paths only)")
        print("default scope: " + ", ".join(d["defaultScope"]))

    emit(data, as_json, text)


def cmd_search(args):
    as_json = args.json
    query = (args.query or "").strip()
    if len(query) < 2:
        die(2, "missing_query", "Search needs at least 2 characters.", as_json)
    if not 1 <= args.limit <= 50:
        die(2, "bad_request", "--limit must be 1 through 50.", as_json)
    scopes = [resolve_scope(raw, as_json) for raw in (args.onlyin or [])]
    if not scopes:
        scopes = default_roots()
        if not scopes:
            die(2, "bad_request", "No default Documents or Desktop folder. Pass --onlyin.", as_json)
    hits = []
    capped = False
    errors = []
    for scope in scopes:
        cmd = ["-onlyin", str(scope)]
        if args.name:
            cmd.extend(["-name", query])
        else:
            cmd.append(query)
        try:
            proc = run_mdfind(cmd, args.timeout)
        except subprocess.TimeoutExpired:
            die(4, "timeout", f"mdfind timed out after {args.timeout}s. No file was opened.", as_json)
        if proc.returncode != 0:
            errors.append((proc.stderr or proc.stdout or "mdfind failed").strip())
            continue
        for line in (proc.stdout or "").splitlines():
            line = line.strip()
            if not line:
                continue
            if blocked(Path(line)):
                continue
            hits.append(line)
            if len(hits) >= args.limit:
                capped = True
                break
        if capped:
            break
    if errors and not hits:
        die(1, "spotlight_error", errors[0], as_json)
    # de-dupe, keep order
    seen = set()
    unique = []
    for hit in hits:
        if hit in seen:
            continue
        seen.add(hit)
        unique.append(hit)
    data = {
        "ok": True,
        "query": query,
        "nameOnly": bool(args.name),
        "scopes": [str(s) for s in scopes],
        "count": len(unique),
        "truncated": capped,
        "paths": unique,
    }

    def text(d):
        print(f"{d['count']} paths" + (" (limit reached)" if d["truncated"] else ""))
        for path in d["paths"]:
            print(path)

    emit(data, as_json, text)


def cmd_gaps(args):
    as_json = getattr(args, "json", False)
    data = {"ok": True, "tool": TOOL, "version": VERSION, "gaps": GAPS}
    if as_json:
        print(json.dumps(data))
        return
    print("grok-spotlight gaps")
    for item in GAPS:
        print(f"- {item}")


def build_parser():
    parser = argparse.ArgumentParser(prog=TOOL, description="Scoped Spotlight search. Paths only.")
    parser.add_argument("--version", action="version", version=f"{TOOL} {VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_json(p):
        p.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor")
    add_json(doctor)
    doctor.set_defaults(func=cmd_doctor)

    search = sub.add_parser("search")
    add_json(search)
    search.add_argument("query")
    search.add_argument("--onlyin", action="append", help="Folder to search. Repeatable. Default is Documents and Desktop.")
    search.add_argument("--name", action="store_true", help="Match file names only (mdfind -name).")
    search.add_argument("--limit", type=int, default=20)
    search.add_argument("--timeout", type=int, default=15)
    search.set_defaults(func=cmd_search)

    gaps = sub.add_parser("gaps")
    add_json(gaps)
    gaps.set_defaults(func=cmd_gaps)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    timeout = getattr(args, "timeout", None)
    if isinstance(timeout, int) and not 1 <= timeout <= 60:
        die(2, "bad_request", "--timeout must be 1 through 60 seconds.", getattr(args, "json", False))
    args.func(args)


if __name__ == "__main__":
    main()
