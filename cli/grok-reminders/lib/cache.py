"""Read ~/.cache/grok-reminders/index.sqlite when present. No Apple Events."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path.home() / ".cache" / "grok-reminders" / "index.sqlite"


def available() -> dict | None:
    if not DB.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            meta = {r[0]: r[1] for r in con.execute("SELECT key, value FROM meta")}
            if meta.get("status") != "ok":
                return None
            rows = int(con.execute("SELECT count(*) FROM reminders").fetchone()[0])
            return {"path": str(DB), "meta": meta, "rows": rows}
        finally:
            con.close()
    except sqlite3.Error:
        return None


def search(query: str, limit: int = 40, list_name: str | None = None) -> dict:
    info = available()
    if not info:
        return {"ok": False, "error": "no_index", "message": "No reminders index. Run: grok-desk reindex --only reminders"}
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        sql = "SELECT id, list_name, title, due, completed FROM reminders WHERE title LIKE ? COLLATE NOCASE "
        args: list = [f"%{query}%"]
        if list_name:
            sql += "AND list_name = ? "
            args.append(list_name)
        sql += "ORDER BY due IS NULL, due LIMIT ?"
        args.append(int(limit))
        rows = []
        for ident, lst, title, due, completed in con.execute(sql, args):
            rows.append({
                "id": ident,
                "list": lst,
                "title": title,
                "due": due or None,
                "completed": bool(completed),
                "priority": "none",
                "flagged": False,
            })
        return {
            "ok": True,
            "source": "cache",
            "query": query,
            "count": len(rows),
            "reminders": rows,
            "path": info["path"],
            "indexedAt": info["meta"].get("indexed_at"),
        }
    finally:
        con.close()


def due_window(start: str, end: str, list_name: str | None = None) -> dict:
    info = available()
    if not info:
        return {"ok": False, "error": "no_index"}
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        sql = (
            "SELECT id, list_name, title, due, completed FROM reminders "
            "WHERE completed = 0 AND due != '' AND substr(due,1,10) >= ? AND substr(due,1,10) <= ? "
        )
        args: list = [start, end]
        if list_name:
            sql += "AND list_name = ? "
            args.append(list_name)
        sql += "ORDER BY due"
        rows = []
        for ident, lst, title, due, completed in con.execute(sql, args):
            rows.append({
                "id": ident,
                "list": lst,
                "title": title,
                "due": due or None,
                "completed": bool(completed),
                "priority": "none",
                "flagged": False,
            })
        return {
            "ok": True,
            "source": "cache",
            "from": start,
            "to": end,
            "count": len(rows),
            "reminders": rows,
            "path": info["path"],
        }
    finally:
        con.close()
