#!/usr/bin/env python3
"""grok-safari: read Safari bookmarks and Reading List from Bookmarks.plist.

Portable for any user on any Mac. Does not modify bookmarks, open URLs, or read
History, passwords, or cookies. to-note can create one Note from a Reading List
item through grok-notes; dry-run is the default.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

VERSION = "0.1.3"
TOOL = "grok-safari"
MAX_LIMIT = 50
DEFAULT_LIMIT = 20
FOLDER_LABELS = {
    "BookmarksBar": "Favorites",
    "BookmarksMenu": "Bookmarks Menu",
}

GAPS = [
    "Reads only ~/Library/Safari/Bookmarks.plist. History, cookies, passwords, iCloud Tabs, and the open-tab session are not read.",
    "If the plist is unreadable, doctor exits needs_full_disk_access once. System Settings is not opened.",
    "Bookmarks and Reading List are local Safari data. They can lag iCloud sync. Nothing is written back to Safari.",
    "Reading List preview text is not returned. Titles and URLs are.",
    "Reading List items are not added, edited, deleted, or opened. URLs are not launched. to-note is the only write path: dry-run by default; --force creates one Note through grok-notes create-note. The note title is the item title and the body is the URL.",
    "Folder names BookmarksBar and BookmarksMenu are shown as Favorites and Bookmarks Menu. Other folders keep the plist title.",
    "A proxy such as History is skipped. It is not a bookmark.",
    "Optional cache under ~/.cache/grok-safari stores bookmark and Reading List rows keyed to Bookmarks.plist mtime. search/bookmarks/reading-list hit the cache first. Clear with cache-clear.",
]


def die(code, error, message, as_json, **extra):
    payload = {
        "ok": False,
        "tool": TOOL,
        "version": VERSION,
        "error": error,
        "code": code,
        "message": message,
    }
    payload.update(extra)
    if as_json:
        print(json.dumps(payload))
    else:
        print("%s: %s" % (TOOL, error), file=sys.stderr)
        if message:
            print(message, file=sys.stderr)
    raise SystemExit(code)


def emit(data, as_json, text_fn):
    if not data.get("ok", False):
        code = data.get("code", 1)
        if as_json:
            data.setdefault("tool", TOOL)
            data.setdefault("version", VERSION)
            data.setdefault("code", code)
            print(json.dumps(data))
        else:
            print("%s: %s: %s" % (TOOL, data.get("error"), data.get("message", "")), file=sys.stderr)
        raise SystemExit(code)
    if as_json:
        data.setdefault("tool", TOOL)
        data.setdefault("version", VERSION)
        print(json.dumps(data))
    else:
        text_fn(data)


def bookmarks_path():
    return Path.home() / "Library" / "Safari" / "Bookmarks.plist"


def cache_dir():
    return Path.home() / ".cache" / "grok-safari"


def cache_db_path():
    return cache_dir() / "index.sqlite"


def ensure_cache_dir():
    path = cache_dir()
    path.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(path, 0o700)
    except OSError:
        pass
    return path


def iso(value):
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.isoformat()
        return value.astimezone().isoformat()
    return None


def iso_mtime(path):
    try:
        return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).astimezone().isoformat()
    except OSError:
        return None


def load_root(as_json):
    import plistlib

    path = bookmarks_path()
    started = time.monotonic()
    try:
        with path.open("rb") as handle:
            data = plistlib.load(handle)
    except FileNotFoundError:
        die(
            5,
            "needs_full_disk_access",
            "Bookmarks.plist is missing. On a fresh Mac, open Safari once so it creates ~/Library/Safari. "
            "System Settings was not opened.",
            as_json,
            hint="Open Safari once, or grant Full Disk Access if the file exists but is unreadable.",
            path=str(path),
        )
    except PermissionError:
        die(
            5,
            "needs_full_disk_access",
            "Bookmarks.plist is not readable. Full Disk Access may be required for this process. "
            "System Settings was not opened.",
            as_json,
            hint="Grant Full Disk Access to the terminal or automation host running grok-safari, then retry doctor.",
            path=str(path),
        )
    except OSError as exc:
        if getattr(exc, "errno", None) in (1, 13):
            die(
                5,
                "needs_full_disk_access",
                "Bookmarks.plist is not readable. Full Disk Access may be required. System Settings was not opened.",
                as_json,
                hint="Grant Full Disk Access, then retry doctor.",
                path=str(path),
            )
        die(1, "unreadable", "Cannot read Bookmarks.plist: %s" % exc, as_json)
    except Exception as exc:  # plistlib.InvalidFileException and friends
        name = type(exc).__name__
        if "Invalid" in name or "plist" in name.lower():
            die(1, "bad_plist", "Bookmarks.plist is not a property list (%s)." % exc, as_json)
        raise
    elapsed = time.monotonic() - started
    if elapsed > 30:
        die(4, "timeout", "Reading Bookmarks.plist took too long (%.1fs)." % elapsed, as_json)
    if not isinstance(data, dict):
        die(1, "bad_plist", "Bookmarks.plist has an unexpected shape.", as_json)
    return data


def leaf_item(node, folder_parts, reading):
    uri = node.get("URIDictionary") if isinstance(node.get("URIDictionary"), dict) else {}
    title = uri.get("title") if isinstance(uri.get("title"), str) else ""
    url = node.get("URLString") if isinstance(node.get("URLString"), str) else ""
    item = {
        "id": node.get("WebBookmarkUUID") if isinstance(node.get("WebBookmarkUUID"), str) else "",
        "title": title,
        "url": url,
    }
    if reading:
        rl = node.get("ReadingList") if isinstance(node.get("ReadingList"), dict) else {}
        item["dateAdded"] = iso(rl.get("DateAdded"))
    else:
        item["folder"] = "/".join(folder_parts)
    return item


def collect(root, full=True):
    """Walk bookmarks. If full is False, only count (lean doctor)."""
    bookmarks = []
    reading = []
    bookmark_count = 0
    reading_count = 0

    def walk(node, folder_parts, in_reading):
        nonlocal bookmark_count, reading_count
        if not isinstance(node, dict):
            return
        title = node.get("Title") if isinstance(node.get("Title"), str) else ""
        kind = node.get("WebBookmarkType")
        if title == "com.apple.ReadingList":
            for child in node.get("Children") or []:
                walk(child, [], True)
            return
        if kind == "WebBookmarkTypeProxy":
            return
        if kind == "WebBookmarkTypeList":
            next_parts = folder_parts
            if title:
                next_parts = folder_parts + [FOLDER_LABELS.get(title, title)]
            for child in node.get("Children") or []:
                walk(child, next_parts, in_reading)
            return
        if kind == "WebBookmarkTypeLeaf":
            is_reading = in_reading or isinstance(node.get("ReadingList"), dict)
            if full:
                item = leaf_item(node, folder_parts, is_reading)
                if is_reading:
                    reading.append(item)
                else:
                    bookmarks.append(item)
            else:
                if is_reading:
                    reading_count += 1
                else:
                    bookmark_count += 1

    walk(root, [], False)
    if full:
        return bookmarks, reading
    return bookmark_count, reading_count


def check_limit(limit, as_json):
    if not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        die(2, "bad_request", "--limit must be 1 through %s." % MAX_LIMIT, as_json)


def clip(items, limit):
    return items[:limit], len(items), len(items) > limit


def plist_meta():
    path = bookmarks_path()
    meta = {
        "path": "Library/Safari/Bookmarks.plist",
        "exists": path.is_file(),
        "readable": False,
        "sizeBytes": None,
        "mtime": None,
    }
    if not path.is_file():
        return meta
    try:
        st = path.stat()
        meta["sizeBytes"] = st.st_size
        meta["mtime"] = iso_mtime(path)
        meta["mtimeEpoch"] = st.st_mtime
    except OSError:
        return meta
    try:
        with path.open("rb") as handle:
            handle.read(1)
        meta["readable"] = True
    except OSError:
        meta["readable"] = False
    return meta


def init_cache_db(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS bookmarks (
            id TEXT,
            title TEXT,
            url TEXT,
            folder TEXT
        );
        CREATE TABLE IF NOT EXISTS reading_list (
            id TEXT,
            title TEXT,
            url TEXT,
            date_added TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_bookmarks_title ON bookmarks(title);
        CREATE INDEX IF NOT EXISTS idx_reading_title ON reading_list(title);
        """
    )


def cache_is_fresh(mtime_epoch):
    path = cache_db_path()
    if not path.is_file():
        return False
    try:
        conn = sqlite3.connect(str(path))
        try:
            row = conn.execute("SELECT value FROM meta WHERE key = 'plist_mtime'").fetchone()
            return bool(row and row[0] == ("%.6f" % mtime_epoch))
        finally:
            conn.close()
    except sqlite3.Error:
        return False


def write_cache(bookmarks, reading, mtime_epoch):
    ensure_cache_dir()
    path = cache_db_path()
    tmp = cache_dir() / "index.sqlite.tmp"
    if tmp.exists():
        try:
            tmp.unlink()
        except OSError:
            pass
    conn = sqlite3.connect(str(tmp))
    try:
        init_cache_db(conn)
        conn.execute("DELETE FROM meta")
        conn.execute("DELETE FROM bookmarks")
        conn.execute("DELETE FROM reading_list")
        conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            ("plist_mtime", "%.6f" % mtime_epoch),
        )
        conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            ("cached_at", datetime.now().astimezone().isoformat()),
        )
        conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?)",
            ("tool_version", VERSION),
        )
        conn.executemany(
            "INSERT INTO bookmarks(id, title, url, folder) VALUES (?, ?, ?, ?)",
            [
                (b.get("id") or "", b.get("title") or "", b.get("url") or "", b.get("folder") or "")
                for b in bookmarks
            ],
        )
        conn.executemany(
            "INSERT INTO reading_list(id, title, url, date_added) VALUES (?, ?, ?, ?)",
            [
                (r.get("id") or "", r.get("title") or "", r.get("url") or "", r.get("dateAdded") or "")
                for r in reading
            ],
        )
        conn.commit()
    finally:
        conn.close()
    os.replace(str(tmp), str(path))
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def read_cache():
    path = cache_db_path()
    conn = sqlite3.connect(str(path))
    try:
        bookmarks = [
            {"id": r[0], "title": r[1], "url": r[2], "folder": r[3]}
            for r in conn.execute("SELECT id, title, url, folder FROM bookmarks")
        ]
        reading = [
            {"id": r[0], "title": r[1], "url": r[2], "dateAdded": r[3] or None}
            for r in conn.execute("SELECT id, title, url, date_added FROM reading_list")
        ]
        return bookmarks, reading
    finally:
        conn.close()


def load_items(as_json, prefer_cache=True):
    meta = plist_meta()
    if not meta["exists"] or not meta["readable"]:
        # Fall through to load_root for consistent error codes/messages.
        root = load_root(as_json)
        bookmarks, reading = collect(root, full=True)
        return bookmarks, reading, False, meta
    mtime_epoch = meta.get("mtimeEpoch")
    if prefer_cache and mtime_epoch is not None and cache_is_fresh(mtime_epoch):
        try:
            bookmarks, reading = read_cache()
            return bookmarks, reading, True, meta
        except sqlite3.Error:
            pass
    root = load_root(as_json)
    bookmarks, reading = collect(root, full=True)
    if mtime_epoch is not None:
        try:
            write_cache(bookmarks, reading, mtime_epoch)
        except (OSError, sqlite3.Error):
            pass
    return bookmarks, reading, False, meta


def cmd_doctor(args):
    as_json = args.json
    meta = plist_meta()
    hints = []
    if not meta["exists"]:
        hints.append("Bookmarks.plist missing. Open Safari once on this Mac so ~/Library/Safari is created.")
        data = {
            "ok": False,
            "error": "needs_full_disk_access",
            "code": 5,
            "message": "Bookmarks.plist is missing.",
            "plist": meta,
            "cacheDir": str(cache_dir()),
            "modifiesBookmarks": False,
            "opensUrls": False,
            "hints": hints,
        }
        emit(data, as_json, lambda d: None)
        return
    if not meta["readable"]:
        hints.append("Grant Full Disk Access to the process running grok-safari, then retry.")
        data = {
            "ok": False,
            "error": "needs_full_disk_access",
            "code": 5,
            "message": "Bookmarks.plist is not readable.",
            "plist": meta,
            "cacheDir": str(cache_dir()),
            "modifiesBookmarks": False,
            "opensUrls": False,
            "hints": hints,
        }
        emit(data, as_json, lambda d: None)
        return
    # Lean: count-only walk, no full item materialization.
    root = load_root(as_json)
    bookmark_count, reading_count = collect(root, full=False)
    cache_fresh = bool(meta.get("mtimeEpoch") is not None and cache_is_fresh(meta["mtimeEpoch"]))
    hints.append("Read-only: no bookmark edits and no URL opens.")
    hints.append("List/search hit ~/.cache/grok-safari when the plist mtime matches.")
    if not cache_fresh:
        hints.append("Cache empty or stale; next bookmarks/reading-list/search will rebuild it.")
    data = {
        "ok": True,
        "plist": {
            "path": meta["path"],
            "readable": True,
            "sizeBytes": meta["sizeBytes"],
            "mtime": meta["mtime"],
        },
        "bookmarkCount": bookmark_count,
        "readingListCount": reading_count,
        "cacheDir": str(cache_dir()),
        "cacheFresh": cache_fresh,
        "modifiesBookmarks": False,
        "opensUrls": False,
        "lean": True,
        "hints": hints,
    }

    def text(d):
        print("grok-safari %s  ok (read-only)" % VERSION)
        print("plist: ~/%s (%s bytes)" % (d["plist"]["path"], d["plist"]["sizeBytes"]))
        print("bookmarks: %s" % d["bookmarkCount"])
        print("reading list: %s" % d["readingListCount"])
        print("cache: %s (fresh=%s)" % (d["cacheDir"], "yes" if d["cacheFresh"] else "no"))
        print("bookmarks: read-only  opens URLs: no  to-note --force creates a Note")
        for hint in d["hints"][:2]:
            print("hint: %s" % hint)

    emit(data, as_json, text)


def cmd_status(args):
    as_json = args.json
    bookmarks, reading, from_cache, meta = load_items(as_json, prefer_cache=True)
    data = {
        "ok": True,
        "plist": {
            "path": meta["path"],
            "readable": meta["readable"],
            "sizeBytes": meta["sizeBytes"],
            "mtime": meta["mtime"],
        },
        "bookmarkCount": len(bookmarks),
        "readingListCount": len(reading),
        "fromCache": from_cache,
        "cacheDir": str(cache_dir()),
        "modifiesBookmarks": False,
        "opensUrls": False,
    }

    def text(d):
        print("grok-safari status")
        print("bookmarks: %s" % d["bookmarkCount"])
        print("reading list: %s" % d["readingListCount"])
        print("from cache: %s" % ("yes" if d["fromCache"] else "no"))
        if d["plist"].get("mtime"):
            print("plist mtime: %s" % d["plist"]["mtime"])

    emit(data, as_json, text)


def cmd_bookmarks(args):
    as_json = args.json
    check_limit(args.limit, as_json)
    bookmarks, _reading, from_cache, _meta = load_items(as_json, prefer_cache=True)
    shown, total, truncated = clip(bookmarks, args.limit)
    data = {
        "ok": True,
        "total": total,
        "count": len(shown),
        "truncated": truncated,
        "fromCache": from_cache,
        "bookmarks": shown,
    }

    def text(d):
        print("%s of %s bookmarks%s" % (d["count"], d["total"], " (cache)" if d["fromCache"] else ""))
        for item in d["bookmarks"]:
            folder = item.get("folder") or "(top)"
            print("%s  %s  %s" % (folder, item.get("title") or "(untitled)", item.get("url") or ""))

    emit(data, as_json, text)


def cmd_reading(args):
    as_json = args.json
    check_limit(args.limit, as_json)
    _bookmarks, reading, from_cache, _meta = load_items(as_json, prefer_cache=True)
    shown, total, truncated = clip(reading, args.limit)
    data = {
        "ok": True,
        "total": total,
        "count": len(shown),
        "truncated": truncated,
        "fromCache": from_cache,
        "readingList": shown,
    }

    def text(d):
        print("%s of %s reading list%s" % (d["count"], d["total"], " (cache)" if d["fromCache"] else ""))
        for item in d["readingList"]:
            print("%s  %s" % (item.get("title") or "(untitled)", item.get("url") or ""))

    emit(data, as_json, text)


def cmd_search(args):
    as_json = args.json
    check_limit(args.limit, as_json)
    query = (args.query or "").strip()
    if len(query) < 2:
        die(2, "missing_query", "Search needs at least 2 characters.", as_json)
    needle = query.casefold()
    bookmarks, reading, from_cache, _meta = load_items(as_json, prefer_cache=True)
    hits = []
    for item in bookmarks:
        blob = "%s %s %s" % (item.get("title") or "", item.get("url") or "", item.get("folder") or "")
        if needle in blob.casefold():
            row = dict(item)
            row["kind"] = "bookmark"
            hits.append(row)
    for item in reading:
        blob = "%s %s" % (item.get("title") or "", item.get("url") or "")
        if needle in blob.casefold():
            row = dict(item)
            row["kind"] = "reading-list"
            hits.append(row)
    shown, total, truncated = clip(hits, args.limit)
    data = {
        "ok": True,
        "query": query,
        "total": total,
        "count": len(shown),
        "truncated": truncated,
        "fromCache": from_cache,
        "hits": shown,
    }

    def text(d):
        print("%s of %s hits%s" % (d["count"], d["total"], " (cache)" if d["fromCache"] else ""))
        for item in d["hits"]:
            print("%s  %s  %s" % (item.get("kind"), item.get("title") or "(untitled)", item.get("url") or ""))

    emit(data, as_json, text)


def cmd_reindex(args):
    as_json = args.json
    meta = plist_meta()
    root = load_root(as_json)
    bookmarks, reading = collect(root, full=True)
    mtime_epoch = meta.get("mtimeEpoch")
    if mtime_epoch is None:
        try:
            mtime_epoch = bookmarks_path().stat().st_mtime
        except OSError as exc:
            die(1, "unreadable", "Cannot stat Bookmarks.plist: %s" % exc, as_json)
    try:
        write_cache(bookmarks, reading, mtime_epoch)
    except (OSError, sqlite3.Error) as exc:
        die(1, "cache_error", "Could not write cache: %s" % exc, as_json)
    data = {
        "ok": True,
        "bookmarkCount": len(bookmarks),
        "readingListCount": len(reading),
        "cacheDir": str(cache_dir()),
        "plistMtime": meta.get("mtime"),
    }

    def text(d):
        print("reindexed %s bookmarks, %s reading list" % (d["bookmarkCount"], d["readingListCount"]))
        print(d["cacheDir"])

    emit(data, as_json, text)


def cmd_cache_clear(args):
    as_json = args.json
    path = cache_db_path()
    removed = False
    if path.is_file():
        try:
            path.unlink()
            removed = True
        except OSError as exc:
            die(1, "cache_error", "Could not clear cache: %s" % exc, as_json)
    data = {"ok": True, "removed": removed, "cacheDir": str(cache_dir())}

    def text(d):
        print("cache cleared" if d["removed"] else "cache already empty")
        print(d["cacheDir"])

    emit(data, as_json, text)


_NOTES = None


def load_notes_cli():
    """The existing grok-notes CLI. Not a second Notes backend."""
    global _NOTES
    if _NOTES is None:
        import importlib.util
        path = Path(__file__).resolve().parents[2] / "grok-notes" / "lib" / "cli.py"
        spec = importlib.util.spec_from_file_location("grok_notes_cli", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _NOTES = mod
    return _NOTES


def apply_note(title, body, folder=None):
    notes = load_notes_cli()
    payload = {"cmd": "create-note", "title": title, "body": body, "html": None, "folder": folder, "account": None, "parent": None, "force": True}
    return notes.call_jxa(payload, 60, False)


def select_reading_item(reading, index=None, url=None, title=None):
    reading = reading or []
    selectors = sum(1 for v in (index is not None, bool(url), bool(title)) if v)
    if selectors == 0:
        return {"ok": False, "error": "missing_target", "message": "Pass --index, --url, or --title for one Reading List item. Nothing was created."}
    if selectors > 1:
        return {"ok": False, "error": "bad_request", "message": "Pass only one of --index, --url, or --title. Nothing was created."}
    if not reading:
        return {"ok": False, "error": "not_found", "message": "Reading List is empty. Nothing was created."}
    if index is not None:
        if index < 1 or index > len(reading):
            return {"ok": False, "error": "bad_index", "message": "Reading List index must be 1 through %s. Nothing was created." % len(reading)}
        item = reading[index - 1]
        return {"ok": True, "item": item, "index": index}
    if url:
        hits = [(i, item) for i, item in enumerate(reading, 1) if (item.get("url") or "") == url]
        if not hits:
            return {"ok": False, "error": "not_found", "message": "No Reading List item with that exact URL. Nothing was created."}
        if len(hits) > 1:
            return {"ok": False, "error": "ambiguous", "message": "More than one Reading List item has that exact URL. Pass --index. Nothing was created."}
        i, item = hits[0]
        return {"ok": True, "item": item, "index": i}
    hits = [(i, item) for i, item in enumerate(reading, 1) if (item.get("title") or "") == title]
    if not hits:
        return {"ok": False, "error": "not_found", "message": "No Reading List item with that exact title. Nothing was created."}
    if len(hits) > 1:
        return {"ok": False, "error": "ambiguous", "message": "More than one Reading List item has that exact title. Pass --index. Nothing was created."}
    i, item = hits[0]
    return {"ok": True, "item": item, "index": i}


def print_to_note(data):
    title = data.get("title") or "(untitled)"
    url = data.get("url") or ""
    if data.get("dryRun"):
        print("dry-run: would create one note")
    else:
        print("created note")
    print("title: %s" % title)
    print("url: %s" % url)
    if data.get("folder"):
        print("folder: %s" % data.get("folder"))
    if data.get("noteId"):
        print("id: %s" % data.get("noteId"))
    if data.get("message"):
        print(data["message"])


def cmd_to_note(args):
    as_json = args.json
    index = args.index
    url = args.url.strip() if isinstance(args.url, str) and args.url.strip() else None
    title = args.title.strip() if isinstance(args.title, str) and args.title.strip() else None
    folder = args.folder.strip() if isinstance(args.folder, str) and args.folder.strip() else None
    chosen = None
    # Validate selectors before touching the Reading List when args alone are enough.
    selectors = sum(1 for v in (index is not None, bool(url), bool(title)) if v)
    if selectors == 0:
        die(2, "missing_target", "Pass --index, --url, or --title for one Reading List item. Nothing was created.", as_json)
    if selectors > 1:
        die(2, "bad_request", "Pass only one of --index, --url, or --title. Nothing was created.", as_json)
    if index is not None and index < 1:
        die(2, "bad_index", "Reading List index must be 1 or greater. Nothing was created.", as_json)
    _bookmarks, reading, from_cache, _meta = load_items(as_json, prefer_cache=True)
    chosen = select_reading_item(reading, index=index, url=url, title=title)
    if not chosen.get("ok"):
        err = chosen.get("error") or "bad_request"
        code = 2 if err in ("missing_target", "bad_request", "bad_index", "ambiguous") else 1
        die(code, err, chosen.get("message") or "Nothing was created.", as_json)
    item = chosen["item"]
    note_title = item.get("title") or "(untitled)"
    note_url = item.get("url") or ""
    if not note_url:
        die(2, "missing_url", "That Reading List item has no URL. Nothing was created.", as_json)
    summary = {
        "ok": True,
        "tool": TOOL,
        "version": VERSION,
        "command": "to-note",
        "dryRun": not args.force,
        "applied": False,
        "index": chosen["index"],
        "title": note_title,
        "url": note_url,
        "folder": folder,
        "fromCache": from_cache,
        "modifiesBookmarks": False,
        "opensUrls": False,
        "bridge": "grok-notes-create-note",
        "note": {"title": note_title, "body": note_url, "folder": folder},
    }
    if not args.force:
        summary["message"] = "dry-run: Reading List was only read. Notes.app was not called. Pass --force to create one note through grok-notes create-note."
        emit(summary, as_json, print_to_note)
        return
    created = apply_note(note_title, note_url, folder=folder)
    if not created.get("ok"):
        # Surface Notes failure through safari emit shape.
        fail = {
            "ok": False,
            "tool": TOOL,
            "version": VERSION,
            "command": "to-note",
            "error": created.get("error") or "notes_error",
            "code": 1,
            "message": created.get("message") or "Notes create-note failed. Nothing was created.",
            "title": note_title,
            "url": note_url,
            "folder": folder,
            "notes": created,
        }
        emit(fail, as_json, print_to_note)
        return
    summary["dryRun"] = False
    summary["applied"] = True
    summary["noteId"] = created.get("id")
    summary["noteAccount"] = created.get("account")
    summary["noteFolder"] = created.get("folder") or created.get("path")
    summary["created"] = created
    summary["message"] = "Created one note through grok-notes create-note. Reading List was not changed."
    emit(summary, as_json, print_to_note)



def cmd_gaps(args):
    as_json = getattr(args, "json", False)
    data = {"ok": True, "tool": TOOL, "version": VERSION, "gaps": GAPS}
    if as_json:
        print(json.dumps(data))
        return
    print("grok-safari gaps")
    for item in GAPS:
        print("- %s" % item)


def build_parser():
    parser = argparse.ArgumentParser(
        prog=TOOL,
        description="Read Safari bookmarks and Reading List on any Mac. Does not edit or open them. to-note creates a Note only with --force.",
    )
    parser.add_argument("--version", action="version", version="%s %s" % (TOOL, VERSION))
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_json(p):
        p.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor", help="Lean read-only readiness check (count-only walk).")
    add_json(doctor)
    doctor.set_defaults(func=cmd_doctor)

    status = sub.add_parser("status", help="Bookmark and Reading List counts (cache-first).")
    add_json(status)
    status.set_defaults(func=cmd_status)

    bookmarks = sub.add_parser("bookmarks", help="List bookmarks (cache-first, default limit 20).")
    add_json(bookmarks)
    bookmarks.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    bookmarks.set_defaults(func=cmd_bookmarks)

    reading = sub.add_parser("reading-list", help="List Reading List (cache-first, default limit 20).")
    add_json(reading)
    reading.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    reading.set_defaults(func=cmd_reading)

    search = sub.add_parser("search", help="Search bookmarks and Reading List (cache-first).")
    add_json(search)
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    search.set_defaults(func=cmd_search)

    reindex = sub.add_parser("reindex", help="Rebuild ~/.cache/grok-safari from Bookmarks.plist.")
    add_json(reindex)
    reindex.set_defaults(func=cmd_reindex)

    cache_clear = sub.add_parser("cache-clear", help="Remove ~/.cache/grok-safari index.")
    add_json(cache_clear)
    cache_clear.set_defaults(func=cmd_cache_clear)

    to_note = sub.add_parser(
        "to-note",
        help="Create one Note from one Reading List item (dry-run unless --force).",
    )
    add_json(to_note)
    to_note.add_argument("--index", type=int, help="1-based index into the Reading List (same order as reading-list).")
    to_note.add_argument("--url", help="Exact Reading List URL.")
    to_note.add_argument("--title", help="Exact Reading List title.")
    to_note.add_argument("--folder", help="Optional Notes folder; passed to grok-notes create-note.")
    to_note.add_argument(
        "--force",
        action="store_true",
        help="Create the note through grok-notes create-note. Without this, Notes is not called.",
    )
    to_note.set_defaults(func=cmd_to_note)

    gaps = sub.add_parser("gaps")
    add_json(gaps)
    gaps.set_defaults(func=cmd_gaps)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
