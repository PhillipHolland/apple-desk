"""Read ~/.cache/grok-contacts/index.sqlite when the index is ok. No Apple Events."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

DB = Path.home() / ".cache" / "grok-contacts" / "index.sqlite"
# grok-desk reports a contacts index as ok when opt-in is set and the table is readable,
# even if the writer has not stored an explicit status key yet.
BAD_STATUS = {"error", "pending_allow", "off", "unreadable", "failed", "skipped"}


def _connect():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)


def available() -> dict | None:
    if not DB.exists():
        return None
    try:
        con = _connect()
        try:
            meta = {r[0]: r[1] for r in con.execute("SELECT key, value FROM meta")}
            status = meta.get("status")
            if status in BAD_STATUS:
                return None
            legacy_ok = status is None and meta.get("indexed_at") and meta.get("opt_in") == "1"
            if status != "ok" and not legacy_ok:
                return None
            people = int(con.execute("SELECT count(*) FROM contacts").fetchone()[0])
            return {"path": str(DB), "meta": meta, "people": people, "status": status or "ok"}
        finally:
            con.close()
    except sqlite3.Error:
        return None


def _row(ident, name, org, phones, emails) -> dict:
    try:
        phone_list = json.loads(phones or "[]")
    except json.JSONDecodeError:
        phone_list = []
    try:
        email_list = json.loads(emails or "[]")
    except json.JSONDecodeError:
        email_list = []
    if not isinstance(phone_list, list):
        phone_list = []
    if not isinstance(email_list, list):
        email_list = []
    return {
        "id": ident,
        "name": name or None,
        "organization": org or None,
        "phones": [str(p) for p in phone_list if p],
        "emails": [str(e) for e in email_list if e],
    }


def _like(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def search(query: str, limit: int = 20, field: str = "name") -> dict:
    info = available()
    if not info:
        return {
            "ok": False,
            "error": "no_index",
            "message": "No contacts index. Run: grok-desk reindex --only contacts",
        }
    q = (query or "").strip()
    if len(q) < 2:
        return {"ok": False, "error": "missing_query", "message": "Search needs at least 2 characters."}
    field = field or "name"
    if field == "phone":
        where = "phones LIKE ? ESCAPE '\\' COLLATE NOCASE"
    elif field == "email":
        where = "emails LIKE ? ESCAPE '\\' COLLATE NOCASE"
    else:
        where = "(name LIKE ? ESCAPE '\\' COLLATE NOCASE OR org LIKE ? ESCAPE '\\' COLLATE NOCASE)"
    needle = _like(q)
    args: list = [needle, needle] if field not in ("phone", "email") else [needle]
    con = _connect()
    try:
        total = int(con.execute(f"SELECT count(*) FROM contacts WHERE {where}", args).fetchone()[0])
        rows = []
        sql = f"SELECT id, name, org, phones, emails FROM contacts WHERE {where} ORDER BY name LIMIT ?"
        for rec in con.execute(sql, args + [int(limit)]):
            rows.append(_row(*rec))
        return {
            "ok": True,
            "source": "cache",
            "query": q,
            "field": field,
            "count": total,
            "truncated": total > len(rows),
            "matches": rows,
            "path": info["path"],
            "indexedAt": info["meta"].get("indexed_at"),
        }
    finally:
        con.close()


def show(query: str | None, ident: str | None) -> dict:
    info = available()
    if not info:
        return {"ok": False, "error": "no_index", "message": "No contacts index. Run: grok-desk reindex --only contacts"}
    con = _connect()
    try:
        if ident:
            rec = con.execute(
                "SELECT id, name, org, phones, emails FROM contacts WHERE id = ?",
                (ident,),
            ).fetchone()
            if not rec:
                return {"ok": False, "error": "not_found", "message": "No contact with that id in the local index."}
            card = _row(*rec)
        else:
            found = search(query or "", limit=20, field="name")
            if not found.get("ok"):
                return found
            matches = found.get("matches") or []
            if found.get("count") == 0:
                return {"ok": False, "error": "not_found", "message": "No contact matched in the local index."}
            if found.get("count") != 1:
                return {
                    "ok": False,
                    "error": "ambiguous",
                    "count": found.get("count"),
                    "message": "More than one contact matched. Run show --id with one id.",
                    "matches": matches,
                    "source": "cache",
                }
            card = matches[0]
        contact = {
            "id": card["id"],
            "name": card["name"],
            "organization": card["organization"],
            "phones": [{"label": None, "value": p, "id": None} for p in card["phones"]],
            "emails": [{"label": None, "value": e, "id": None} for e in card["emails"]],
            "groups": [],
        }
        return {
            "ok": True,
            "source": "cache",
            "contact": contact,
            "path": info["path"],
            "indexedAt": info["meta"].get("indexed_at"),
        }
    finally:
        con.close()


def summary(info: dict | None = None) -> dict:
    info = info or available()
    if not info:
        return {"ok": False, "error": "no_index", "message": "No contacts index. Run: grok-desk reindex --only contacts"}
    return {
        "ok": True,
        "source": "cache",
        "automation": "not_checked",
        "backend": "contacts-index",
        "readOnly": False,
        "contactsApp": None,
        "people": info["people"],
        "groups": None,
        "groupNames": [],
        "hasMeCard": None,
        "indexedAt": info["meta"].get("indexed_at"),
        "path": info["path"],
        "status": info["status"],
        "note": "Doctor used the local index (people count only). It did not open Contacts.app. Pass --live for a light Automation check.",
    }
