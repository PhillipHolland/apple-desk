#!/usr/bin/env python3
"""grok-safari: read Safari bookmarks and Reading List from Bookmarks.plist.

Does not modify bookmarks, open URLs, or read History, passwords, or cookies.
"""
from __future__ import annotations

import argparse
import json
import plistlib
import sys
from datetime import datetime
from pathlib import Path

VERSION = "0.1.0"
TOOL = "grok-safari"
MAX_LIMIT = 50
FOLDER_LABELS = {
    "BookmarksBar": "Favorites",
    "BookmarksMenu": "Bookmarks Menu",
}

GAPS = [
    "Reads only ~/Library/Safari/Bookmarks.plist. History, cookies, passwords, iCloud Tabs, and the open-tab session are not read.",
    "If the plist is unreadable, doctor exits needs_full_disk_access once. System Settings is not opened.",
    "Bookmarks and Reading List are local Safari data. They can lag iCloud sync. Nothing is written back.",
    "Reading List preview text is not returned. Titles and URLs are.",
    "There is no add, delete, move, or open. URLs are not launched.",
    "Folder names BookmarksBar and BookmarksMenu are shown as Favorites and Bookmarks Menu. Other folders keep the plist title.",
    "A proxy such as History is skipped. It is not a bookmark.",
]


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


def load_root(as_json):
    path = bookmarks_path()
    try:
        with path.open("rb") as handle:
            data = plistlib.load(handle)
    except FileNotFoundError:
        die(5, "needs_full_disk_access", "Bookmarks.plist is missing. System Settings was not opened.", as_json)
    except PermissionError:
        die(
            5,
            "needs_full_disk_access",
            "Bookmarks.plist is not readable. Full Disk Access may be required for this process. System Settings was not opened.",
            as_json,
        )
    except OSError as exc:
        if getattr(exc, "errno", None) in (1, 13):
            die(
                5,
                "needs_full_disk_access",
                "Bookmarks.plist is not readable. Full Disk Access may be required. System Settings was not opened.",
                as_json,
            )
        die(1, "unreadable", "Cannot read Bookmarks.plist: %s" % exc, as_json)
    except plistlib.InvalidFileException as exc:
        die(1, "bad_plist", "Bookmarks.plist is not a property list (%s)." % exc, as_json)
    if not isinstance(data, dict):
        die(1, "bad_plist", "Bookmarks.plist has an unexpected shape.", as_json)
    return data


def iso(value):
    if isinstance(value, datetime):
        return value.isoformat()
    return None


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


def collect(root):
    bookmarks = []
    reading = []

    def walk(node, folder_parts, in_reading):
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
            item = leaf_item(node, folder_parts, is_reading)
            if is_reading:
                reading.append(item)
            else:
                bookmarks.append(item)

    walk(root, [], False)
    return bookmarks, reading


def check_limit(limit, as_json):
    if not isinstance(limit, int) or not 1 <= limit <= MAX_LIMIT:
        die(2, "bad_request", "--limit must be 1 through %s." % MAX_LIMIT, as_json)


def clip(items, limit):
    return items[:limit], len(items), len(items) > limit


def cmd_doctor(args):
    as_json = args.json
    root = load_root(as_json)
    bookmarks, reading = collect(root)
    data = {
        "ok": True,
        "path": "Library/Safari/Bookmarks.plist",
        "readable": True,
        "bookmarkCount": len(bookmarks),
        "readingListCount": len(reading),
        "modifiesBookmarks": False,
        "opensUrls": False,
    }

    def text(d):
        print("grok-safari %s  ok" % VERSION)
        print("bookmarks: %s" % d["bookmarkCount"])
        print("reading list: %s" % d["readingListCount"])

    emit(data, as_json, text)


def cmd_bookmarks(args):
    as_json = args.json
    check_limit(args.limit, as_json)
    bookmarks, _reading = collect(load_root(as_json))
    shown, total, truncated = clip(bookmarks, args.limit)
    data = {"ok": True, "total": total, "count": len(shown), "truncated": truncated, "bookmarks": shown}

    def text(d):
        print("%s of %s bookmarks" % (d["count"], d["total"]))
        for item in d["bookmarks"]:
            folder = item.get("folder") or "(top)"
            print("%s  %s  %s" % (folder, item.get("title") or "(untitled)", item.get("url") or ""))

    emit(data, as_json, text)


def cmd_reading(args):
    as_json = args.json
    check_limit(args.limit, as_json)
    _bookmarks, reading = collect(load_root(as_json))
    shown, total, truncated = clip(reading, args.limit)
    data = {"ok": True, "total": total, "count": len(shown), "truncated": truncated, "readingList": shown}

    def text(d):
        print("%s of %s reading list" % (d["count"], d["total"]))
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
    bookmarks, reading = collect(load_root(as_json))
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
    data = {"ok": True, "query": query, "total": total, "count": len(shown), "truncated": truncated, "hits": shown}

    def text(d):
        print("%s of %s hits" % (d["count"], d["total"]))
        for item in d["hits"]:
            print("%s  %s  %s" % (item.get("kind"), item.get("title") or "(untitled)", item.get("url") or ""))

    emit(data, as_json, text)


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
    parser = argparse.ArgumentParser(prog=TOOL, description="Read Safari bookmarks and Reading List. Does not edit or open them.")
    parser.add_argument("--version", action="version", version="%s %s" % (TOOL, VERSION))
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_json(p):
        p.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor")
    add_json(doctor)
    doctor.set_defaults(func=cmd_doctor)

    bookmarks = sub.add_parser("bookmarks")
    add_json(bookmarks)
    bookmarks.add_argument("--limit", type=int, default=20)
    bookmarks.set_defaults(func=cmd_bookmarks)

    reading = sub.add_parser("reading-list")
    add_json(reading)
    reading.add_argument("--limit", type=int, default=20)
    reading.set_defaults(func=cmd_reading)

    search = sub.add_parser("search")
    add_json(search)
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)
    search.set_defaults(func=cmd_search)

    gaps = sub.add_parser("gaps")
    add_json(gaps)
    gaps.set_defaults(func=cmd_gaps)
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
