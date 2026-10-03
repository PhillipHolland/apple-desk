#!/usr/bin/env python3
"""grok-desk 0.1.4 — onboard a Mac and build local search indexes.

Caches stay under ~/.cache (0700 dirs, 0600 databases). Nothing is uploaded.
No Keychain. No Passwords. Mail is not called. Calendar and Reminders are
called only by reindex, once each, and only through their CLIs.
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
import calendar_index
import reminders_index

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
    "Calendar reindex runs grok-calendar doctor once. When that is authorized it stores calendar names and events in a portable window: past 30 days through the next 90 days (override with --past-days/--future-days or GROK_CALENDAR_PAST_DAYS and GROK_CALENDAR_FUTURE_DAYS, each 0..366). One calendar index at a time (uid, title, start, end, all-day, calendar name). Only the Apple system calendar titled Scheduled Reminders is skipped by name. A wide window that times out is read in 14-day slices, and each slice is retried once. A slice over 800 events is split further by date. Doctor timeout or denied Automation sets pending_allow and is not retried. Locations and notes are not stored. grok-calendar list/search and grok-desk search read this cache first.",
    "Reminders reindex runs a names-only doctor, lean lists, then one incomplete-only collect (id, list, title, due). Notes are not stored. Timeout or denied Automation sets pending_allow and is not retried. Mail is not indexed. Focus and Safari are probed by doctor and are not part of this index.",
    "Keychain, Passwords, and HomeKit are out on purpose.",
    "An optional one-line signature lives in ~/.config/grok-desk/signature. grok-desk does not send messages and does not append that line.",
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
    sig = data.get("signature")
    if isinstance(sig, dict) and "signature" not in sig:
        print("  signature: " + ("set" if sig.get("set") else "unset"))
    elif isinstance(sig, dict) and sig.get("set") and sig.get("signature"):
        print(sig["signature"])
    elif isinstance(sig, dict):
        print("signature: unset")


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
            if name == "calendar":
                row["calendars"] = _count(con, "calendars")
                row["windowFrom"] = meta.get("window_from")
                row["windowTo"] = meta.get("window_to")
                row["pastDays"] = meta.get("past_days")
                row["futureDays"] = meta.get("future_days")
            if name == "reminders":
                row["lists"] = _count(con, "lists")
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


def reindex_surface(name: str, full: bool, index_contacts: bool, past_days: int | None = None, future_days: int | None = None) -> dict:
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
        return calendar_index.build(past_days=past_days, future_days=future_days)
    if name == "reminders":
        return reminders_index.build()
    return {"ok": False, "surface": name, "error": "unknown_surface"}


def do_reindex(full: bool, only: str | None, index_contacts: bool, past_days: int | None = None, future_days: int | None = None) -> dict:
    if only:
        names = [only]
        if only == "contacts":
            index_contacts = True
    else:
        names = ["notes", "messages", "calendar", "reminders"]
        if index_contacts:
            names.append("contacts")
    indexes = [reindex_surface(name, full, index_contacts, past_days, future_days) for name in names]
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



def _fts_query(text: str) -> str:
    """Quoted AND of alphanumeric tokens. Empty when nothing is searchable."""
    parts = []
    token = []
    for ch in text:
        if ch.isalnum():
            token.append(ch)
        else:
            if len(token) >= 2:
                parts.append('"' + "".join(token) + '"')
            token = []
    if len(token) >= 2:
        parts.append('"' + "".join(token) + '"')
    return " AND ".join(parts[:8])


def do_search(surface: str, query: str, limit: int) -> dict:
    """Query a local index when present. No Apple Events."""
    import sqlite3
    q = (query or "").strip()
    if len(q) < 2:
        return {"ok": False, "error": "missing_query", "message": "Search needs at least 2 characters."}
    path = common.db_path(f"grok-{surface}")
    if not path.exists():
        return {"ok": False, "error": "no_index", "message": f"No {surface} index. Run: grok-desk reindex --only {surface}"}
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        meta = _meta(con)
        if meta.get("status") == "pending_allow":
            return {"ok": False, "error": "pending_allow", "message": f"{surface} index is pending_allow. Fix Automation, then reindex."}
        needle = f"%{q}%"
        rows = []
        if surface == "calendar":
            for uid, cal, title, start_at, end_at, all_day in con.execute(
                "SELECT uid, calendar, title, start_at, end_at, all_day FROM events "
                "WHERE title LIKE ? COLLATE NOCASE ORDER BY start_at LIMIT ?",
                (needle, limit),
            ):
                rows.append({"uid": uid, "calendar": cal, "title": title, "start": start_at, "end": end_at, "allDay": bool(all_day)})
        elif surface == "reminders":
            for ident, lst, title, due, completed in con.execute(
                "SELECT id, list_name, title, due, completed FROM reminders "
                "WHERE title LIKE ? COLLATE NOCASE ORDER BY due IS NULL, due LIMIT ?",
                (needle, limit),
            ):
                rows.append({"id": ident, "list": lst, "title": title, "due": due or None, "completed": bool(completed)})
        elif surface == "contacts":
            for ident, name, org in con.execute(
                "SELECT id, name, org FROM contacts WHERE name LIKE ? COLLATE NOCASE OR org LIKE ? COLLATE NOCASE LIMIT ?",
                (needle, needle, limit),
            ):
                rows.append({"id": ident, "name": name, "org": org})
        elif surface == "notes":
            try:
                fts = _fts_query(q)
                seen = set()
                if fts:
                    for row in con.execute(
                        "SELECT id, title, folder FROM notes WHERE rowid IN ("
                        "SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?) LIMIT ?",
                        (fts, limit),
                    ):
                        seen.add(row[0])
                        rows.append({"id": row[0], "title": row[1], "folder": row[2]})
                if len(rows) < limit:
                    for row in con.execute(
                        "SELECT id, title, folder FROM notes WHERE title LIKE ? COLLATE NOCASE LIMIT ?",
                        (needle, limit),
                    ):
                        if row[0] in seen:
                            continue
                        rows.append({"id": row[0], "title": row[1], "folder": row[2]})
                        if len(rows) >= limit:
                            break
            except sqlite3.OperationalError as exc:
                return {"ok": False, "error": "schema", "message": str(exc)[:200]}
        elif surface == "messages":
            try:
                seen = set()
                for row in con.execute(
                    "SELECT guid, display_name, last_message_date FROM chats "
                    "WHERE display_name LIKE ? COLLATE NOCASE LIMIT ?",
                    (needle, limit),
                ):
                    seen.add(row[0])
                    rows.append({"chatGuid": row[0], "name": row[1], "lastDate": row[2]})
                fts = _fts_query(q)
                if fts and len(rows) < limit:
                    for row in con.execute(
                        "SELECT DISTINCT chat_guid FROM message_fts WHERE message_fts MATCH ? LIMIT ?",
                        (fts, limit),
                    ):
                        guid = row[0]
                        if not guid or guid in seen:
                            continue
                        chat = con.execute(
                            "SELECT display_name, last_message_date FROM chats WHERE guid = ?",
                            (guid,),
                        ).fetchone()
                        seen.add(guid)
                        rows.append({
                            "chatGuid": guid,
                            "name": None if chat is None else chat[0],
                            "lastDate": None if chat is None else chat[1],
                            "matched": "text",
                        })
                        if len(rows) >= limit:
                            break
            except sqlite3.OperationalError as exc:
                return {"ok": False, "error": "schema", "message": str(exc)[:200]}
        else:
            return {"ok": False, "error": "unknown_surface", "message": surface}
        return {
            "ok": True,
            "tool": common.TOOL,
            "version": VERSION,
            "surface": surface,
            "source": "cache",
            "query": q,
            "count": len(rows),
            "hits": rows,
            "path": str(path),
            "indexedAt": meta.get("indexed_at"),
        }
    finally:
        con.close()


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
    reindex.add_argument("--past-days", type=int, default=None, help="Calendar window before today (default 30, or GROK_CALENDAR_PAST_DAYS)")
    reindex.add_argument("--future-days", type=int, default=None, help="Calendar window after today (default 90, or GROK_CALENDAR_FUTURE_DAYS)")
    add_json(reindex)

    status = sub.add_parser("status", help="Cache paths, counts, timestamps, size")
    add_json(status)

    gaps = sub.add_parser("gaps", help="What this tool will not do")
    add_json(gaps)

    search = sub.add_parser("search", help="Search a local index (no Apple Events)")
    search.add_argument("surface", choices=SURFACES)
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)
    add_json(search)

    signature = sub.add_parser("signature", help="Show or set the one-line outgoing signature")
    signature.add_argument("--set", dest="set_text", default=None, help="Store one line. Does not send anything.")
    signature.add_argument("--clear", action="store_true", help="Remove the stored line")
    add_json(signature)
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
        data = {
            "ok": True,
            "tool": common.TOOL,
            "version": VERSION,
            "tools": probe_tools(),
            "caches": probe_caches(),
            "signature": {"set": common.read_signature() is not None, "path": str(common.signature_path())},
        }
        emit(data, as_json)
        return 0
    if args.cmd == "gaps":
        data = {"ok": True, "tool": common.TOOL, "version": VERSION, "gaps": GAPS}
        emit(data, as_json)
        return 0
    if args.cmd == "status":
        data = {
            "ok": True,
            "tool": common.TOOL,
            "version": VERSION,
            "summary": status_rows(),
            "signatureSet": common.read_signature() is not None,
        }
        emit(data, as_json)
        return 0
    if args.cmd == "reindex":
        data = do_reindex(args.full, args.only, args.index_contacts, getattr(args, "past_days", None), getattr(args, "future_days", None))
        emit(data, as_json)
        return 0 if data["ok"] else 1
    if args.cmd == "onboard":
        data = do_onboard(args.full, args.index_contacts)
        emit(data, as_json)
        return 0 if data["ok"] else 1
    if args.cmd == "search":
        data = do_search(args.surface, args.query, args.limit)
        emit(data, as_json)
        return 0 if data.get("ok") else 1
    if args.cmd == "signature":
        if args.clear and args.set_text is not None:
            die(2, "bad_request", "Pass either --set or --clear, not both.", as_json)
        if args.clear:
            common.clear_signature()
            data = {"ok": True, "tool": common.TOOL, "version": VERSION, "signature": {"set": False, "path": str(common.signature_path())}}
            emit(data, as_json)
            return 0
        if args.set_text is not None:
            try:
                line = common.write_signature(args.set_text)
            except ValueError as exc:
                die(2, "bad_signature", str(exc), as_json)
            data = {
                "ok": True,
                "tool": common.TOOL,
                "version": VERSION,
                "signature": {"set": True, "signature": line, "path": str(common.signature_path())},
            }
            emit(data, as_json)
            return 0
        line = common.read_signature()
        if line is None:
            die(2, "unset", 'No signature stored. Ask the user, then grok-desk signature --set "...".', as_json)
        data = {
            "ok": True,
            "tool": common.TOOL,
            "version": VERSION,
            "signature": {"set": True, "signature": line, "path": str(common.signature_path())},
        }
        emit(data, as_json)
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
