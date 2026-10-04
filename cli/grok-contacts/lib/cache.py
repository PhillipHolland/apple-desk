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


# Exact queries. Stored labels differ from the Shortcuts words parent and sibling.
RELATION_ALIASES = {
    "parent": ("parent", "mother", "father"),
    "sibling": ("sibling", "brother", "sister"),
}


def _columns(con) -> set[str]:
    return {row[1] for row in con.execute("PRAGMA table_info(contacts)")}


def _blank(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _relationships(raw) -> list[dict]:
    try:
        data = json.loads(raw or "[]")
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out = []
    for item in data:
        if isinstance(item, dict):
            label = _blank(item.get("label"))
            name = _blank(item.get("name"))
            if not label and not name:
                continue
            out.append({"id": None, "label": label, "name": name})
        elif isinstance(item, str) and item.strip():
            out.append({"id": None, "label": item.strip(), "name": None})
    return out


def _row(ident, name, org, phones, emails, nickname=None, relationships=None, have_extra=False) -> dict:
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
    row = {
        "id": ident,
        "name": name or None,
        "organization": org or None,
        "phones": [str(p) for p in phone_list if p],
        "emails": [str(e) for e in email_list if e],
    }
    if have_extra:
        row["nickname"] = _blank(nickname)
        row["relationships"] = _relationships(relationships)
    return row


def _needs_reindex(field: str) -> dict:
    return {
        "ok": False,
        "error": "needs_reindex",
        "field": field,
        "message": (
            "This contacts index has no nickname or relationship columns yet. "
            "Run: grok-desk reindex --only contacts"
        ),
    }


def _like(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _field_where(field: str, query: str, cols: set[str]) -> tuple[str, list, str | None]:
    """Return SQL where, args, and an error code if this index cannot answer."""
    field = field or "name"
    if field == "phone":
        return "phones LIKE ? ESCAPE '\\' COLLATE NOCASE", [_like(query)], None
    if field == "email":
        return "emails LIKE ? ESCAPE '\\' COLLATE NOCASE", [_like(query)], None
    if field == "nickname":
        if "nickname" not in cols:
            return "", [], "needs_reindex"
        return "nickname LIKE ? ESCAPE '\\' COLLATE NOCASE", [_like(query)], None
    if field == "relationship":
        if "rel_labels" not in cols:
            return "", [], "needs_reindex"
        aliases = RELATION_ALIASES.get(query.lower())
        if aliases:
            parts = []
            args = []
            for label in aliases:
                parts.append("rel_labels LIKE ? ESCAPE '\\' COLLATE NOCASE")
                args.append(_like("\n" + label + "\n"))
            return "(" + " OR ".join(parts) + ")", args, None
        return "rel_labels LIKE ? ESCAPE '\\' COLLATE NOCASE", [_like(query)], None
    return (
        "(name LIKE ? ESCAPE '\\' COLLATE NOCASE OR org LIKE ? ESCAPE '\\' COLLATE NOCASE)",
        [_like(query), _like(query)],
        None,
    )


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
    con = _connect()
    try:
        cols = _columns(con)
        where, args, problem = _field_where(field, q, cols)
        if problem == "needs_reindex":
            return _needs_reindex(field)
        have_extra = "nickname" in cols and "relationships" in cols
        nickname_sql = "nickname" if "nickname" in cols else "NULL"
        rel_sql = "relationships" if "relationships" in cols else "NULL"
        total = int(con.execute(f"SELECT count(*) FROM contacts WHERE {where}", args).fetchone()[0])
        rows = []
        sql = (
            f"SELECT id, name, org, phones, emails, {nickname_sql}, {rel_sql} "
            f"FROM contacts WHERE {where} ORDER BY name LIMIT ?"
        )
        for rec in con.execute(sql, args + [int(limit)]):
            rows.append(_row(*rec, have_extra=have_extra))
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
        cols = _columns(con)
        have_extra = "nickname" in cols and "relationships" in cols
        nickname_sql = "nickname" if "nickname" in cols else "NULL"
        rel_sql = "relationships" if "relationships" in cols else "NULL"
        select = f"SELECT id, name, org, phones, emails, {nickname_sql}, {rel_sql} FROM contacts"
        if ident:
            rec = con.execute(select + " WHERE id = ?", (ident,)).fetchone()
            if not rec:
                return {"ok": False, "error": "not_found", "message": "No contact with that id in the local index."}
            card = _row(*rec, have_extra=have_extra)
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
        if have_extra:
            contact["nickname"] = card.get("nickname")
            contact["relationships"] = card.get("relationships") or []
        result = {
            "ok": True,
            "source": "cache",
            "contact": contact,
            "path": info["path"],
            "indexedAt": info["meta"].get("indexed_at"),
        }
        if not have_extra:
            result["fieldsNote"] = (
                "This index has no nickname or relationship columns. "
                "show --live reads them from Contacts. "
                "Run: grok-desk reindex --only contacts"
            )
        return result
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
