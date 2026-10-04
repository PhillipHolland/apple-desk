#!/usr/bin/env python3
"""Local Notes search index under ~/.cache/grok-notes.

Default reindex stores titles, folders, and dates only. Pass index_bodies
to store note bodies. That file is as sensitive as Notes.app. cache-clear
deletes the index only.
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path

CACHE_DIR = Path.home() / ".cache" / "grok-notes"
DB_PATH = CACHE_DIR / "index.sqlite"
SCHEMA = "1"
BODY_CAP = 200000
def clean_text(value):
    """Drop lone UTF-16 surrogates that JXA JSON sometimes leaves in note text."""
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    if not value:
        return ""
    return value.encode("utf-16", "surrogatepass").decode("utf-16", "replace")


TOKEN_RE = re.compile(r"[0-9A-Za-z\u00C0-\uFFFF]+")
TAG_RE = re.compile(r"(?:^|\s)#([A-Za-z][\w/-]{0,64})")


def ensure_cache():
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(CACHE_DIR, 0o700)


def connect():
    ensure_cache()
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=DELETE")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db(con):
    ver = None
    try:
        row = con.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        if row:
            ver = row[0]
    except sqlite3.OperationalError:
        ver = None
    if ver != SCHEMA:
        con.executescript(
            """
            DROP TABLE IF EXISTS notes_fts;
            DROP TABLE IF EXISTS notes;
            DROP TABLE IF EXISTS folders;
            DROP TABLE IF EXISTS meta;
            """
        )
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS folders (
          id TEXT PRIMARY KEY,
          name TEXT,
          account TEXT,
          parent TEXT,
          path TEXT,
          depth INTEGER,
          shared INTEGER,
          trash INTEGER
        );
        CREATE TABLE IF NOT EXISTS notes (
          rowid INTEGER PRIMARY KEY,
          id TEXT UNIQUE,
          title TEXT,
          folder TEXT,
          folder_id TEXT,
          folder_path TEXT,
          account TEXT,
          parent TEXT,
          modified TEXT,
          created TEXT,
          locked INTEGER,
          shared INTEGER,
          trash INTEGER,
          snippet TEXT,
          body TEXT,
          body_chars INTEGER,
          truncated INTEGER
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS notes_fts USING fts5(
          title, body, folder_path,
          content='notes', content_rowid='rowid',
          tokenize="unicode61 remove_diacritics 1"
        );
        """
    )
    con.execute("INSERT INTO meta(key, value) VALUES('schema', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (SCHEMA,))
    con.commit()
    os.chmod(DB_PATH, 0o600)


def clear_cache():
    removed = []
    if CACHE_DIR.exists():
        for p in CACHE_DIR.iterdir():
            if p.is_file():
                p.unlink()
                removed.append(p.name)
    return {"ok": True, "removed": removed, "path": str(CACHE_DIR)}


def status():
    if not DB_PATH.exists():
        return {"ok": True, "exists": False, "path": str(DB_PATH), "notes": 0, "folders": 0}
    con = connect()
    try:
        init_db(con)
        notes = con.execute("SELECT count(*) FROM notes").fetchone()[0]
        folders = con.execute("SELECT count(*) FROM folders").fetchone()[0]
        meta = {r["key"]: r["value"] for r in con.execute("SELECT key, value FROM meta")}
    finally:
        con.close()
    updated = meta.get("indexed_at")
    age = None
    if updated:
        try:
            then = datetime.fromisoformat(updated.replace("Z", "+00:00"))
            age = max(0, int((datetime.now(timezone.utc) - then).total_seconds()))
        except ValueError:
            age = None
    return {
        "ok": True,
        "exists": True,
        "path": str(DB_PATH),
        "notes": notes,
        "folders": folders,
        "indexedAt": updated,
        "ageSeconds": age,
        "mode": meta.get("mode"),
        "warnings": int(meta.get("warnings") or 0),
        "schema": meta.get("schema"),
    }


def _norm_note(n, body):
    text = body if isinstance(body, str) else ""
    if len(text) > BODY_CAP:
        text = text[:BODY_CAP]
        truncated = True
    else:
        truncated = bool(n.get("truncated"))
    snippet = n.get("snippet") if isinstance(n.get("snippet"), str) else ""
    if text and not snippet:
        snippet = " ".join(text.split())[:400]
    return {
        "id": n.get("id"),
        "title": clean_text(n.get("title") or ""),
        "folder": clean_text(n.get("folder") or ""),
        "folder_id": clean_text(n.get("folderId") or n.get("folder_id") or ""),
        "folder_path": clean_text(n.get("folderPath") or n.get("folder_path") or n.get("folder") or ""),
        "account": clean_text(n.get("account") or ""),
        "parent": clean_text(n.get("parent") or ""),
        "modified": n.get("modified") or "",
        "created": n.get("created") or "",
        "locked": 1 if n.get("locked") else 0,
        "shared": 1 if n.get("shared") else 0,
        "trash": 1 if n.get("trash") else 0,
        "snippet": "" if n.get("locked") else clean_text(snippet),
        "body": "" if n.get("locked") else clean_text(text),
        "body_chars": 0 if n.get("locked") else len(text),
        "truncated": 1 if truncated else 0,
    }


def _save(con, rows, folders, mode, warnings, seconds, index_bodies=False):
    init_db(con)
    con.execute("DELETE FROM notes")
    con.execute("DELETE FROM folders")
    con.executemany(
        """
        INSERT INTO folders(id, name, account, parent, path, depth, shared, trash)
        VALUES (:id, :name, :account, :parent, :path, :depth, :shared, :trash)
        """,
        [
            {
                "id": f.get("id"),
                "name": clean_text(f.get("name") or ""),
                "account": clean_text(f.get("account") or ""),
                "parent": clean_text(f.get("parent") or ""),
                "path": clean_text(f.get("path") or f.get("name") or ""),
                "depth": int(f.get("depth") or 0),
                "shared": 1 if f.get("shared") else 0,
                "trash": 1 if f.get("trash") else 0,
            }
            for f in folders
            if f.get("id")
        ],
    )
    con.executemany(
        """
        INSERT INTO notes(
          id, title, folder, folder_id, folder_path, account, parent, modified, created,
          locked, shared, trash, snippet, body, body_chars, truncated
        ) VALUES (
          :id, :title, :folder, :folder_id, :folder_path, :account, :parent, :modified, :created,
          :locked, :shared, :trash, :snippet, :body, :body_chars, :truncated
        )
        """,
        rows,
    )
    con.execute("INSERT INTO notes_fts(notes_fts) VALUES('rebuild')")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for key, value in {
        "schema": SCHEMA,
        "indexed_at": now,
        "mode": mode,
        "warnings": str(len(warnings)),
        "seconds": f"{seconds:.2f}",
        "bodies": "1" if index_bodies else "0",
    }.items():
        con.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, value),
        )
    con.commit()
    if not index_bodies:
        con.execute("VACUUM")
    os.chmod(DB_PATH, 0o600)


def _load_old(con):
    init_db(con)
    old = {}
    for r in con.execute("SELECT * FROM notes"):
        old[r["id"]] = dict(r)
    return old


def _reindex_metadata(jxa, include_trash, t0):
    """Titles, folders, and dates only. Does not read or keep note bodies."""
    meta = jxa({"cmd": "export", "mode": "stamp", "includeTrash": include_trash}, timeout=120)
    if not meta.get("ok"):
        return meta
    warnings = list(meta.get("warnings") or [])
    rows = []
    for n in meta.get("notes") or []:
        if not n.get("id"):
            continue
        row = _norm_note(n, "")
        row["body"] = ""
        row["snippet"] = ""
        row["body_chars"] = 0
        rows.append(row)
    folders = []
    for f in meta.get("folders") or []:
        if not f.get("id"):
            continue
        folders.append({
            "id": f.get("id"),
            "name": f.get("name") or "",
            "account": f.get("account") or "",
            "parent": f.get("parent") or "",
            "path": f.get("path") or f.get("name") or "",
            "depth": int(f.get("depth") or 0),
            "shared": bool(f.get("shared")),
            "trash": bool(f.get("trash")),
        })
    stats = {
        "mode": "metadata",
        "added": len(rows),
        "bodiesRefreshed": 0,
        "unchanged": 0,
        "removed": 0,
        "indexBodies": False,
    }
    con = connect()
    try:
        seconds = time.time() - t0
        _save(con, rows, folders, stats["mode"], warnings, seconds, index_bodies=False)
    finally:
        con.close()
    trash = sum(1 for f in folders if f.get("trash"))
    return {
        "ok": True,
        "notes": len(rows),
        "folders": len(folders),
        "trashFolders": trash,
        "includeTrash": bool(include_trash),
        "warnings": warnings,
        "seconds": round(time.time() - t0, 2),
        "path": str(DB_PATH),
        "indexBodies": False,
        **stats,
    }


def _bodies_already_indexed(con):
    """True when this index already stores note bodies.

    A metadata reindex records bodies=0. An older index has body text and no flag.
    --index-bodies keeps that copy and only rereads changed notes.
    """
    try:
        row = con.execute("SELECT value FROM meta WHERE key='bodies'").fetchone()
    except sqlite3.OperationalError:
        return False
    if row is not None and row[0] == "1":
        return True
    if row is not None and row[0] == "0":
        return False
    try:
        count = con.execute("SELECT count(*) FROM notes WHERE length(ifnull(body, '')) > 0").fetchone()[0]
    except sqlite3.OperationalError:
        return False
    return bool(count)


def reindex(jxa, full=False, include_trash=False, index_bodies=False):
    t0 = time.time()
    ensure_cache()
    if not index_bodies:
        return _reindex_metadata(jxa, include_trash, t0)
    exists = DB_PATH.exists() and DB_PATH.stat().st_size > 0
    bodies_on = False
    if exists:
        con = connect()
        try:
            bodies_on = _bodies_already_indexed(con)
        finally:
            con.close()
    use_full = full or not exists or not bodies_on
    warnings = []
    if use_full:
        data = jxa({"cmd": "export", "mode": "full", "includeTrash": include_trash}, timeout=180)
        if not data.get("ok"):
            return data
        warnings = list(data.get("warnings") or [])
        rows = [_norm_note(n, n.get("body") or "") for n in data.get("notes") or [] if n.get("id")]
        folders = data.get("folders") or []
        stats = {
            "mode": "full",
            "added": len(rows),
            "bodiesRefreshed": len(rows),
            "unchanged": 0,
            "removed": 0,
        }
    else:
        meta = jxa({"cmd": "export", "mode": "stamp", "includeTrash": include_trash}, timeout=120)
        if not meta.get("ok"):
            return meta
        warnings.extend(meta.get("warnings") or [])
        con = connect()
        try:
            old = _load_old(con)
            old_folders = {r["id"]: dict(r) for r in con.execute("SELECT * FROM folders")}
        finally:
            con.close()
        incoming = [n for n in (meta.get("notes") or []) if n.get("id")]
        dirty_folders = set()
        dirty_ids = set()
        for n in incoming:
            prev = old.get(n["id"])
            folder_id = n.get("folderId") or ""
            modified = n.get("modified") or ""
            locked = 1 if n.get("locked") else 0
            title = n.get("title") or ""
            if (
                not prev
                or (prev.get("modified") or "") != modified
                or (prev.get("folder_id") or "") != folder_id
                or (prev.get("title") or "") != title
            ):
                dirty_folders.add(folder_id)
                dirty_ids.add(n["id"])
        bodies = {}
        if dirty_folders:
            body_data = jxa(
                {
                    "cmd": "export",
                    "mode": "bodies",
                    "includeTrash": include_trash,
                    "folderIds": [fid for fid in dirty_folders if fid],
                },
                timeout=180,
            )
            if not body_data.get("ok"):
                return body_data
            warnings.extend(body_data.get("warnings") or [])
            for n in body_data.get("notes") or []:
                if n.get("id"):
                    bodies[n["id"]] = n
        rows = []
        added = refreshed = unchanged = 0
        new_ids = set()
        for n in incoming:
            new_ids.add(n["id"])
            prev = old.get(n["id"])
            if n["id"] in bodies:
                row = _norm_note(n, bodies[n["id"]].get("body") or "")
                refreshed += 1
                if not prev:
                    added += 1
            elif prev and n["id"] not in dirty_ids:
                row = _norm_note(n, prev.get("body") or "")
                unchanged += 1
            else:
                row = _norm_note(n, "")
                refreshed += 1
                if not prev:
                    added += 1
            rows.append(row)
        removed = len(set(old) - new_ids)
        stamp_folders = meta.get("folders") or []
        structure_changed = False
        for f in stamp_folders:
            prev_f = old_folders.get(f.get("id"))
            if not prev_f or (prev_f.get("name") or "") != (f.get("name") or "") or (prev_f.get("account") or "") != (f.get("account") or ""):
                structure_changed = True
                break
        if len(stamp_folders) != len(old_folders):
            structure_changed = True
        if structure_changed:
            live = jxa({"cmd": "folders"}, timeout=90)
            if not live.get("ok"):
                return live
            folders = live.get("folders") or []
        else:
            folders = []
            for f in stamp_folders:
                prev_f = old_folders.get(f.get("id")) or {}
                folders.append({
                    "id": f.get("id"),
                    "name": f.get("name") or "",
                    "account": f.get("account") or "",
                    "parent": prev_f.get("parent") or "",
                    "path": prev_f.get("path") or f.get("name") or "",
                    "depth": prev_f.get("depth") or 0,
                    "shared": bool(prev_f.get("shared")),
                    "trash": bool(f.get("trash")),
                })
        folder_by_id = {}
        for f in folders:
            if f.get("id"):
                folder_by_id[f["id"]] = f
        for row in rows:
            prev = old.get(row["id"]) or {}
            known = folder_by_id.get(row["folder_id"]) or old_folders.get(row["folder_id"]) or {}
            if known.get("path"):
                row["folder_path"] = known.get("path")
            if known.get("parent"):
                row["parent"] = known.get("parent") or ""
            if not row.get("created"):
                row["created"] = prev.get("created") or ""
            if row["id"] not in bodies and prev:
                row["shared"] = prev.get("shared") or 0
                if not row.get("locked"):
                    row["locked"] = prev.get("locked") or 0
        stats = {
            "mode": "incremental",
            "added": added,
            "bodiesRefreshed": refreshed,
            "unchanged": unchanged,
            "removed": removed,
            "dirtyFolders": len(dirty_folders),
        }
    con = connect()
    try:
        seconds = time.time() - t0
        _save(con, rows, folders, stats["mode"], warnings, seconds, index_bodies=True)
    finally:
        con.close()
    trash = sum(1 for f in folders if f.get("trash"))
    return {
        "ok": True,
        "notes": len(rows),
        "folders": len(folders),
        "trashFolders": trash,
        "includeTrash": bool(include_trash),
        "warnings": warnings,
        "seconds": round(time.time() - t0, 2),
        "path": str(DB_PATH),
        "indexBodies": True,
        **stats,
    }


def build_match(query):
    raw = (query or "").strip()
    if len(raw) >= 2 and raw[0] == raw[-1] == '"':
        inner = raw[1:-1].strip()
        parts = TOKEN_RE.findall(inner)
        if not parts:
            return None
        return '"' + " ".join(parts) + '"'
    parts = TOKEN_RE.findall(raw)
    if not parts:
        return None
    return " AND ".join('"' + p.replace('"', "") + '"' for p in parts)


def _filters(folder, account):
    sql = " AND n.trash = 0"
    params = []
    if folder:
        sql += " AND (n.folder = ? OR n.folder_path = ?)"
        params.extend([folder, folder])
    if account:
        sql += " AND n.account = ?"
        params.append(account)
    return sql, params


def _match_kind(title, body, folder_path, query):
    tokens = [t.casefold() for t in TOKEN_RE.findall(query or "")]
    title_c = (title or "").casefold()
    body_c = (body or "").casefold()
    path_c = (folder_path or "").casefold()
    in_t = any(t in title_c for t in tokens) if tokens else False
    in_b = any(t in body_c for t in tokens) if tokens else False
    if in_t and in_b:
        return "title+body"
    if in_t:
        return "title"
    if in_b:
        return "body"
    if any(t in path_c for t in tokens):
        return "folder"
    return "text"


def _pack(row, query, source):
    snip = (row["snip"] if "snip" in row.keys() else None) or row["snippet"] or ""
    if not snip and row["body"]:
        snip = " ".join((row["body"] or "").split())[:180]
    snip = " ".join(str(snip).split())[:180]
    return {
        "id": row["id"],
        "title": row["title"] or "(untitled)",
        "folder": row["folder"],
        "path": row["folder_path"],
        "account": row["account"],
        "parent": row["parent"] or None,
        "modified": row["modified"],
        "locked": bool(row["locked"]),
        "shared": bool(row["shared"]),
        "match": _match_kind(row["title"], row["body"], row["folder_path"], query),
        "snippet": snip,
        "source": source,
    }


def search(query, limit=20, folder=None, account=None):
    st = status()
    if not st.get("exists"):
        return {
            "ok": False,
            "error": "no_index",
            "message": "No search index yet. Run: grok-notes reindex",
        }
    limit = max(1, min(int(limit or 20), 200))
    tokens = TOKEN_RE.findall(query or "")
    match = build_match(query)
    con = connect()
    try:
        init_db(con)
        if not tokens:
            return {
                "ok": False,
                "error": "missing_query",
                "message": "search needs a text query",
            }
        where = ["n.trash = 0"]
        params = []
        for tok in tokens:
            where.append("(instr(lower(n.title), ?) > 0 OR instr(lower(n.body), ?) > 0 OR instr(lower(n.folder_path), ?) > 0)")
            needle = tok.casefold()
            params.extend([needle, needle, needle])
        if folder:
            where.append("(n.folder = ? OR n.folder_path = ?)")
            params.extend([folder, folder])
        if account:
            where.append("n.account = ?")
            params.append(account)
        sql_where = " WHERE " + " AND ".join(where)
        fetched = con.execute(f"SELECT n.* FROM notes n{sql_where}", params).fetchall()
        ranks = {}
        if match:
            try:
                filt, fparams = _filters(folder, account)
                for row in con.execute(
                    f"""
                    SELECT n.id AS id, bm25(notes_fts) AS rank,
                           snippet(notes_fts, 1, '', '', '…', 18) AS snip
                    FROM notes_fts JOIN notes n ON n.rowid = notes_fts.rowid
                    WHERE notes_fts MATCH ?{filt}
                    """,
                    [match, *fparams],
                ):
                    ranks[row["id"]] = (row["rank"], row["snip"] or "")
            except sqlite3.OperationalError:
                ranks = {}
        ordered = list(fetched)
        ordered.sort(key=lambda r: r["modified"] or "", reverse=True)
        ordered.sort(key=lambda r: (0 if r["id"] in ranks else 1, ranks.get(r["id"], (0, ""))[0]))
        total = len(ordered)
        notes = []
        for r in ordered[:limit]:
            item = dict(r)
            item["snip"] = ranks.get(r["id"], (None, ""))[1] or ""
            notes.append(_pack(item, query, "cache"))
    finally:
        con.close()
    return {
        "ok": True,
        "query": query,
        "source": "cache",
        "bodySearch": True,
        "index": st,
        "total": total,
        "truncated": total > len(notes),
        "limit": limit,
        "notes": notes,
    }


def list_tags(limit=50, folder=None):
    st = status()
    if not st.get("exists"):
        return {"ok": False, "error": "no_index", "message": "No search index yet. Run: grok-notes reindex"}
    counts = {}
    shown = {}
    con = connect()
    sql = "SELECT title, body FROM notes WHERE trash = 0"
    params = []
    if folder:
        sql += " AND (folder = ? OR folder_path = ?)"
        params.extend([folder, folder])
    try:
        for title, body in con.execute(sql, params):
            blob = f"{title or ''}\n{body or ''}"
            for tag in TAG_RE.findall(blob):
                key = tag.casefold()
                counts[key] = counts.get(key, 0) + 1
                shown.setdefault(key, tag)
    finally:
        con.close()
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    limit = max(1, min(int(limit or 50), 500))
    tags = [{"tag": shown[k], "count": counts[k]} for k, _ in ranked[:limit]]
    return {
        "ok": True,
        "source": "cache",
        "folder": folder,
        "total": len(ranked),
        "truncated": len(ranked) > len(tags),
        "tags": tags,
        "index": st,
    }


def cached_folders():
    st = status()
    if not st.get("exists"):
        return {"ok": False, "error": "no_index", "message": "No folder cache yet. Run: grok-notes reindex"}
    con = connect()
    try:
        rows = [dict(r) for r in con.execute("SELECT * FROM folders ORDER BY account, path")]
    finally:
        con.close()
    grouped = {}
    order = []
    for r in rows:
        acct = r["account"]
        if acct not in grouped:
            grouped[acct] = []
            order.append(acct)
        grouped[acct].append(
            {
                "name": r["name"],
                "id": r["id"],
                "parent": r["parent"] or None,
                "path": r["path"],
                "depth": r["depth"],
                "shared": bool(r["shared"]),
                "trash": bool(r["trash"]),
                "account": acct,
            }
        )
    accounts = [{"account": a, "folders": grouped[a]} for a in order]
    flat = [f for a in accounts for f in a["folders"]]
    return {"ok": True, "source": "cache", "index": st, "accounts": accounts, "folders": flat}
