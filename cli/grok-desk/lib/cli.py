#!/usr/bin/env python3
"""grok-desk 0.1.0 — onboard a Mac and build local search indexes.

Caches stay under ~/.cache (0700 dirs, 0600 databases). Nothing is uploaded.
No Keychain. No Passwords. Calendar, Reminders, and Mail are not called.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import common
import contacts_index
import messages_index
import stubs

VERSION = common.VERSION
SAFE_DOCTORS = (
    "grok-notes",
    "grok-contacts",
    "grok-messages",
    "grok-shortcuts",
    "grok-icloud",
    "grok-spotlight",
    "grok-focus",
    "grok-safari",
)
SURFACES = ("notes", "messages", "contacts", "calendar", "reminders")

GAPS = [
    "Indexes are local SQLite files under ~/.cache. grok-desk never uploads them and never copies chat.db.",
    "Notes uses the existing grok-notes cache (~/.cache/grok-notes/index.sqlite). There is no second notes database.",
    "Messages stores chat guid, display name, group flag, service, last date, and message count, plus an FTS index of message text when Full Disk Access allows the read. Send rules are unchanged: grok-messages --to is 1:1 only; groups need --chat-guid.",
    "The contacts cache (id, name, org, phones, emails) is off unless onboard --index-contacts or reindex --only contacts. It is not built by a normal onboard.",
    "Calendar and Reminders caches are empty schemas with status pending_allow. This version does not call those apps, so it cannot hang on an Automation dialog. Filling them waits until Allow is already granted.",
    "Mail is not indexed. Focus and Safari CLIs are probed by doctor and are not part of this build.",
    "Keychain, Passwords, and HomeKit are out on purpose.",
]


def die(code: int, error: str, message: str, as_json: bool) -> None:
    payload = {"ok": False, "tool": common.TOOL, "version": VERSION, "error": error, "message": message}
    if as_json:
        print(json.dumps(payload))
    else:
        print(f"{error}: {message}", file=sys.stderr)
    raise SystemExit(code)


def emit(data: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data))
        return
    print(f"grok-desk {data.get('version', VERSION)}")
    if data.get("error"):
        print(f"{data['error']}: {data.get('message', '')}")
    for tool in data.get("tools") or []:
        mark = "yes" if tool.get("present") else "no"
        print(f"  {tool['name']}: {mark}  {tool.get('version') or ''}")
    for cache in data.get("caches") or []:
        print(
            f"  cache {cache['name']}: exists={cache.get('exists')} bytes={cache.get('bytes', 0)} {cache.get('path', '')}"
        )
    for row in data.get("indexes") or []:
        bits = [f"{k}={v}" for k, v in row.items() if k not in ("message", "detail") and not isinstance(v, (dict, list))]
        print("  " + " ".join(bits))
    for line in data.get("gaps") or []:
        print(f"- {line}")
    if "summary" in data and isinstance(data["summary"], list):
        for row in data["summary"]:
            print(
                f"  {row.get('name')}: rows={row.get('rows')} status={row.get('status')} "
                f"bytes={row.get('bytes')} indexed={row.get('indexedAt')}"
            )


def probe_tools() -> list[dict]:
    tools = []
    for name in common.TOOLS:
        path = common.which(name)
        short = name.removeprefix("grok-")
        entry = {"name": short, "bin": name, "present": bool(path), "path": path}
        if path:
            entry["version"] = common.version_of(path)
            entry["versionOnly"] = name in common.VERSION_ONLY
        tools.append(entry)
    return tools


def probe_caches() -> list[dict]:
    home_cache = Path.home() / ".cache"
    names = list(common.CACHE_NAMES)
    if home_cache.exists():
        for child in sorted(home_cache.glob("grok-*")):
            if child.is_dir() and child.name not in names:
                names.append(child.name)
    out = []
    for name in names:
        folder = common.cache_dir(name)
        db = folder / "index.sqlite"
        out.append(
            {
                "name": name.removeprefix("grok-"),
                "path": str(folder),
                "exists": folder.exists(),
                "db": str(db) if db.exists() else None,
                "bytes": common.dir_bytes(folder),
            }
        )
    return out


def _meta(con: sqlite3.Connection) -> dict:
    try:
        return {row[0]: row[1] for row in con.execute("SELECT key, value FROM meta")}
    except sqlite3.OperationalError:
        return {}


def _count(con: sqlite3.Connection, table: str) -> int | None:
    try:
        return int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
    except sqlite3.OperationalError:
        return None


def status_rows() -> list[dict]:
    specs = [
        ("notes", "notes", "indexed_at"),
        ("messages", "chats", "indexed_at"),
        ("contacts", "contacts", "indexed_at"),
        ("calendar", "events", "indexed_at"),
        ("reminders", "reminders", "indexed_at"),
    ]
    rows = []
    for name, table, when_key in specs:
        folder = common.cache_dir(f"grok-{name}")
        path = common.db_path(f"grok-{name}")
        row = {
            "name": name,
            "path": str(path),
            "exists": path.exists(),
            "bytes": common.dir_bytes(folder),
            "rows": 0,
            "indexedAt": None,
            "status": "missing",
        }
        if not path.exists():
            if name == "contacts":
                row["status"] = "off"
            elif name in ("calendar", "reminders"):
                row["status"] = "not_stubbed"
            rows.append(row)
            continue
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            meta = _meta(con)
            count = _count(con, table)
            row["rows"] = 0 if count is None else count
            row["indexedAt"] = meta.get(when_key)
            row["status"] = meta.get("status") or ("ok" if count is not None else "unreadable")
            if name == "messages":
                row["ftsRows"] = _count(con, "message_fts")
                row["mode"] = meta.get("mode")
            if name == "notes":
                row["folders"] = _count(con, "folders")
                row["mode"] = meta.get("mode")
            if name == "contacts" and meta.get("opt_in") != "1":
                row["status"] = meta.get("status") or "present"
        finally:
            con.close()
        rows.append(row)
    return rows


def reindex_notes(full: bool) -> dict:
    path = common.which("grok-notes")
    if not path:
        return {"ok": False, "surface": "notes", "error": "missing_cli", "message": "grok-notes is not on PATH."}
    cmd = [path, "reindex", "--json"]
    if full:
        cmd.append("--full")
    result = common.run_cmd(cmd, 180)
    if result.get("error") == "timeout":
        return {
            "ok": False,
            "surface": "notes",
            "error": "timeout",
            "message": "grok-notes reindex exceeded 180s. Not retried.",
        }
    summary = {"ok": result.get("ok"), "surface": "notes", "code": result.get("code")}
    raw = result.get("stdout") or ""
    try:
        data = json.loads(raw) if raw.startswith("{") else {}
    except json.JSONDecodeError:
        data = {}
    for key in ("ok", "mode", "notes", "folders", "added", "unchanged", "removed", "bodiesRefreshed", "seconds", "path", "error", "message"):
        if key in data:
            summary[key] = data[key]
    if not data:
        summary["ok"] = False
        summary["error"] = summary.get("error") or "notes_reindex_failed"
        summary["message"] = (result.get("stderr") or "grok-notes reindex did not return JSON.")[:200]
    summary["delegated"] = True
    return summary


def reindex_surface(name: str, full: bool, index_contacts: bool) -> dict:
    if name == "notes":
        return reindex_notes(full)
    if name == "messages":
        return messages_index.build(full=full)
    if name == "contacts":
        if not index_contacts:
            return {
                "ok": True,
                "surface": "contacts",
                "status": "skipped",
                "message": "Contacts index is off unless --index-contacts or --only contacts.",
            }
        return contacts_index.build()
    if name == "calendar":
        return stubs.calendar()
    if name == "reminders":
        return stubs.reminders()
    return {"ok": False, "surface": name, "error": "unknown_surface"}


def do_reindex(full: bool, only: str | None, index_contacts: bool) -> dict:
    if only:
        names = [only]
        if only == "contacts":
            index_contacts = True
    else:
        names = ["notes", "messages", "calendar", "reminders"]
        if index_contacts:
            names.append("contacts")
    indexes = [reindex_surface(name, full, index_contacts) for name in names]
    ok = all(item.get("ok") for item in indexes)
    return {"ok": ok, "tool": common.TOOL, "version": VERSION, "indexes": indexes}


def safe_doctors() -> list[dict]:
    results = []
    for name in common.TOOLS:
        path = common.which(name)
        short = name.removeprefix("grok-")
        if not path:
            results.append({"name": short, "present": False, "checked": "missing"})
            continue
        version = common.version_of(path)
        if name in common.VERSION_ONLY or name not in SAFE_DOCTORS:
            results.append({"name": short, "present": True, "checked": "version", "version": version})
            continue
        doctor = common.run_cmd([path, "doctor", "--json"], 5)
        entry = {"name": short, "present": True, "checked": "doctor", "version": version, "ok": doctor.get("ok")}
        if doctor.get("error") == "timeout":
            entry["ok"] = False
            entry["error"] = "timeout"
            entry["message"] = "doctor exceeded 5s and was not retried"
        elif doctor.get("stdout", "").startswith("{"):
            try:
                data = json.loads(doctor["stdout"])
            except json.JSONDecodeError:
                data = {}
            entry["ok"] = bool(data.get("ok", doctor.get("ok")))
            if data.get("error"):
                entry["error"] = data.get("error")
            if data.get("code"):
                entry["code"] = data.get("code")
        elif not doctor.get("ok"):
            entry["error"] = "doctor_failed"
            entry["code"] = doctor.get("code")
        results.append(entry)
    return results


def do_onboard(full: bool, index_contacts: bool) -> dict:
    links = [common.link_if_needed(name) for name in ("grok-desk",) + common.TOOLS]
    doctors = safe_doctors()
    indexed = do_reindex(full, None, index_contacts)
    ok = indexed["ok"]
    return {
        "ok": ok,
        "tool": common.TOOL,
        "version": VERSION,
        "links": links,
        "doctors": doctors,
        "indexes": indexed["indexes"],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="grok-desk", description="Local Apple Desk onboarding and indexes.")
    parser.add_argument("--version", action="version", version=f"grok-desk {VERSION}")
    sub = parser.add_subparsers(dest="cmd")

    def add_json(command):
        command.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor", help="Which CLIs and caches exist")
    add_json(doctor)

    onboard = sub.add_parser("onboard", help="Link missing bins, safe checks, then reindex")
    onboard.add_argument("--full", action="store_true")
    onboard.add_argument("--index-contacts", action="store_true", help="Opt in to the contacts phone/email cache")
    add_json(onboard)

    reindex = sub.add_parser("reindex", help="Build or update local caches")
    reindex.add_argument("--full", action="store_true")
    reindex.add_argument("--only", choices=SURFACES)
    reindex.add_argument("--index-contacts", action="store_true")
    add_json(reindex)

    status = sub.add_parser("status", help="Cache paths, counts, timestamps, size")
    add_json(status)

    gaps = sub.add_parser("gaps", help="What this tool will not do")
    add_json(gaps)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    as_json = bool(getattr(args, "json", False))
    if not args.cmd:
        parser.print_help()
        return 2
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    if args.cmd == "doctor":
        data = {"ok": True, "tool": common.TOOL, "version": VERSION, "tools": probe_tools(), "caches": probe_caches()}
        emit(data, as_json)
        return 0
    if args.cmd == "gaps":
        data = {"ok": True, "tool": common.TOOL, "version": VERSION, "gaps": GAPS}
        emit(data, as_json)
        return 0
    if args.cmd == "status":
        data = {"ok": True, "tool": common.TOOL, "version": VERSION, "summary": status_rows()}
        emit(data, as_json)
        return 0
    if args.cmd == "reindex":
        data = do_reindex(args.full, args.only, args.index_contacts)
        emit(data, as_json)
        return 0 if data["ok"] else 1
    if args.cmd == "onboard":
        data = do_onboard(args.full, args.index_contacts)
        emit(data, as_json)
        return 0 if data["ok"] else 1
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
