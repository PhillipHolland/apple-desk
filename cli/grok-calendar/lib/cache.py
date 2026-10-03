"""Read ~/.cache/grok-calendar/index.sqlite when present. No Apple Events."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB = Path.home() / ".cache" / "grok-calendar" / "index.sqlite"


def available() -> dict | None:
    if not DB.exists():
        return None
    try:
        con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
        try:
            meta = {r[0]: r[1] for r in con.execute("SELECT key, value FROM meta")}
            if meta.get("status") != "ok":
                return None
            events = int(con.execute("SELECT count(*) FROM events").fetchone()[0])
            return {"path": str(DB), "meta": meta, "events": events}
        finally:
            con.close()
    except sqlite3.Error:
        return None


def list_events(start: str, end: str, calendar: str | None, query: str | None, limit: int) -> dict:
    info = available()
    if not info:
        return {"ok": False, "error": "no_index", "message": "No calendar index. Run: grok-desk reindex --only calendar"}
    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    try:
        sql = (
            "SELECT uid, calendar, title, start_at, end_at, all_day FROM events "
            "WHERE start_at < ? AND (end_at = '' OR end_at > ?) "
        )
        # start_at/end_at are ISO local strings; lexical compare works for ISO-8601
        end_bound = end if "T" in end else end + "T23:59:59"
        start_bound = start if "T" in start else start + "T00:00:00"
        args: list = [end_bound, start_bound]
        if calendar:
            sql += "AND calendar = ? "
            args.append(calendar)
        if query:
            sql += "AND (title LIKE ? COLLATE NOCASE) "
            args.append(f"%{query}%")
        count_sql = "SELECT count(*) FROM (" + sql + ") AS hits"
        total = int(con.execute(count_sql, args).fetchone()[0])
        sql += "ORDER BY start_at LIMIT ?"
        args.append(int(limit))
        rows = []
        for uid, cal, title, start_at, end_at, all_day in con.execute(sql, args):
            rows.append({
                "uid": uid,
                "title": title,
                "start": start_at,
                "end": end_at,
                "allDay": bool(all_day),
                "calendar": cal,
                "location": None,
            })
        return {
            "ok": True,
            "source": "cache",
            "query": query,
            "from": start,
            "to": end,
            "count": len(rows),
            "truncated": total > len(rows),
            "events": rows,
            "path": info["path"],
            "indexedAt": info["meta"].get("indexed_at"),
        }
    finally:
        con.close()
