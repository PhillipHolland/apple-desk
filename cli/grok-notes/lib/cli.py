#!/usr/bin/env python3
"""grok-notes command line. Notes.app via JXA; search via the local cache."""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
from pathlib import Path

import index as indexlib
import markdown_notes

VERSION = "0.2.3"
ROOT = Path(__file__).resolve().parent.parent
LIB = Path(__file__).resolve().parent / "notes.js"

GAPS = [
    "Pin and unpin are not in the Notes scripting dictionary (checked Notes 4.13 on macOS 27).",
    "Lock and unlock are not scriptable. password protected is read-only. This CLI never asks for the Notes password.",
    "Share is read-only. You can see the shared flag. You cannot start a share, copy a collaboration link, or co-edit.",
    "Checklist items can be added as HTML <li>, and existing <li> text can be read. Notes rewrote checked/done/class attributes off <li> on write, so toggling checked is not reliable. promote-checklist does not mark the line done. The backlink is plain text on the reminder (note id and title) because the link-a-note UI is not scriptable.",
    "Drawings, handwriting, scans, tables, PencilKit, audio, and transcription are not scriptable.",
    "Attachments can be listed (name, id, URL, content id) but not added, saved, or removed.",
    "Tags are hashtags in the note text, not a tag object. There are no smart folders.",
    "Formatting that survives is whatever Notes keeps in HTML (div, lists, simple markup). Mentions and the link-a-note UI are not scriptable.",
    "Recently Deleted is a real folder. delete-note moves a note there; delete-note --permanent or empty-trash --force deletes it for good. The app's Delete All UI is not a separate command.",
    "Duplicate is refused by Notes itself (error: Notes can not be copied) on Notes 4.13.",
    "NoteStore.sqlite is intentionally unused (Full Disk Access and schema risk). Club / Viticci NotesCTL is a different tool and is not installed here.",
    "import-md and export-md convert a Markdown subset through Notes HTML. They are a dry-run unless --force. Import will not change an existing title. Export will not overwrite --out unless --replace. File > Import Markdown and File > Export To > Markdown are menu items only (not in the Notes 4.13 scripting dictionary). A checked round-trip kept three heading sizes, bullets, numbered lists, bold, italic, strike, links, simple pipe-table text, and fenced code. Level-4 headings match a subheading. A nested item is stored as a sibling list. Block quotes become paragraphs. Footnotes stay literal. Task markers stay list text, not a Notes checklist. Images become links, not attachments. Code-fence language is dropped. Drawings, scans, and named attachment bytes are omitted.",
]

LI_RE = re.compile(r"<li\b([^>]*)>(.*?)</li>", re.I | re.S)
TAG_RE = re.compile(r"<[^>]+>")
HREF_RE = re.compile(r'href="([^"]+)"', re.I)


def parse_checklist(html_text):
    items = []
    for attrs, inner in LI_RE.findall(html_text or ""):
        checked = bool(re.search(r"\bchecked\b|\bdone\s*=", attrs or "", re.I))
        text = html.unescape(TAG_RE.sub("", inner or "")).strip()
        if text:
            items.append({"text": text, "checked": checked})
    return items


def parse_links(html_text):
    return HREF_RE.findall(html_text or "")[:30]


def die(code, error, message, as_json):
    if as_json:
        print(json.dumps({"ok": False, "tool": "grok-notes", "version": VERSION, "error": error, "code": code, "message": message}))
    else:
        print(f"grok-notes: {error}", file=sys.stderr)
        if message:
            print(message, file=sys.stderr)
        if error in ("automation_denied", "automation_timeout"):
            print("Grant Notes to the app that ran this command:", file=sys.stderr)
            print("System Settings → Privacy & Security → Automation → Grok Bot Helper (or Terminal) → Notes.", file=sys.stderr)
    raise SystemExit(code)


def call_jxa(payload, timeout, as_json):
    proc = subprocess.run(
        ["perl", "-e", "alarm shift @ARGV; exec @ARGV", str(timeout), "osascript", "-l", "JavaScript", str(LIB), "--", json.dumps(payload)],
        capture_output=True,
        text=True,
    )
    detail = (proc.stderr or "") + ("\n" + proc.stdout if proc.returncode else "")
    if proc.returncode in (-14, 142) or "Alarm clock" in (proc.stderr or ""):
        die(4, "automation_timeout", f"Timed out after {timeout}s waiting for Notes.app.", as_json)
    if proc.returncode != 0:
        blob = proc.stderr or proc.stdout or "osascript failed"
        if "-1743" in blob or "Not authorized to send Apple events" in blob:
            die(3, "automation_denied", blob.strip(), as_json)
        if "-1712" in blob or "timed out" in blob.lower():
            die(4, "automation_timeout", blob.strip(), as_json)
        die(1, "notes_error", blob.strip(), as_json)
    raw = (proc.stdout or "").strip()
    if not raw:
        die(1, "notes_error", "Notes returned an empty response", as_json)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        die(1, "notes_error", "Notes returned non-JSON: " + raw[:400], as_json)
    return data


def emit(data, as_json, text_fn):
    if not data.get("ok", False):
        code = 2 if data.get("error") in ("needs_force", "needs_allow_large", "unsupported", "missing_target", "missing_title", "missing_name", "missing_change", "missing_text", "missing_query", "missing_folder", "ambiguous", "bad_request", "already_exists", "file_exists", "missing_path", "missing_out", "empty_markdown", "bad_encoding", "too_large", "missing_line", "bad_index", "no_checklist", "missing_id") else 1
        if as_json:
            data.setdefault("tool", "grok-notes")
            data.setdefault("version", VERSION)
            print(json.dumps(data))
        else:
            print(f"grok-notes: {data.get('error')}: {data.get('message', '')}", file=sys.stderr)
        raise SystemExit(code)
    if as_json:
        print(json.dumps(data))
    else:
        text_fn(data)


def stale_note():
    print("Search index is unchanged until you run: grok-notes reindex", file=sys.stderr)


def print_doctor(data):
    app = data.get("notesApp") or {}
    idx = data.get("index") or {}
    print(f"grok-notes {data.get('version')}  ok")
    print("backend: Notes.app JXA (interim; not MacStories NotesCTL)")
    print(f"automation: {data.get('automation')}")
    print(f"writes: enabled (delete still needs --force)")
    print(f"Notes {app.get('version')} ({app.get('id')})")
    print(f"accounts: {data.get('accounts')}   folders: {data.get('folders')}")
    if idx.get("exists"):
        age = idx.get("ageSeconds")
        age_s = f"{age}s ago" if age is not None else "unknown age"
        print(f"index: {idx.get('notes')} notes, {idx.get('folders')} folders, updated {age_s}")
        print(f"cache: {idx.get('path')}")
    else:
        print("index: none — run grok-notes reindex")
    print("gaps: grok-notes gaps")


def print_folders(data):
    source = data.get("source")
    if source:
        print(f"source: {source}")
    for acct in data.get("accounts") or []:
        print(acct.get("account"))
        folders = list(acct.get("folders") or [])
        normal = [f for f in folders if not f.get("trash")]
        trash = [f for f in folders if f.get("trash")]
        normal.sort(key=lambda f: (f.get("path") or f.get("name") or "").lower())
        for f in normal:
            depth = int(f.get("depth") or 0)
            flags = []
            if f.get("shared"):
                flags.append("shared")
            flag = f"  [{', '.join(flags)}]" if flags else ""
            print(f"{'  ' * (depth + 1)}{f.get('name')}{flag}")
        for f in trash:
            print(f"  {f.get('name')}  (trash; not in the search index unless reindex --include-trash)")


def print_list(data):
    groups = data.get("groups") or []
    if not groups:
        print(f"No folder named {data.get('folder')!r}.")
        return
    for g in groups:
        parent = g.get("parent")
        loc = f"{g.get('account')} / {g.get('folder')}"
        if parent:
            loc += f" (in {parent})"
        print(f"{loc}  ({g.get('count')} notes)")
        for n in g.get("notes") or []:
            when = (n.get("modified") or "")[:16].replace("T", " ")
            title = n.get("title") or "(untitled)"
            print(f"  {title}" + (f"  [{when}]" if when else ""))
        if g.get("truncated"):
            print(f"  … {g.get('count') - len(g.get('notes') or [])} more (raise --limit)")


def print_show(data):
    notes = data.get("notes") or []
    if not notes:
        print("No note with that exact title or id.")
        return
    for n in notes:
        loc = " / ".join(x for x in (n.get("account"), n.get("path") or n.get("folder")) if x)
        flags = []
        if n.get("shared"):
            flags.append("shared")
        if n.get("locked"):
            flags.append("locked")
        flag = f"  [{', '.join(flags)}]" if flags else ""
        print(f"{loc} — {n.get('title')}{flag}")
        print(f"id: {n.get('id')}")
        if n.get("locked"):
            print("(locked — body skipped)")
            continue
        if n.get("readError"):
            print(f"(unreadable: {n.get('readError')})")
            continue
        items = parse_checklist(n.get("html") or "")
        if items:
            print("checklist:")
            for i, item in enumerate(items, 1):
                mark = "x" if item["checked"] else " "
                print(f"  {i}. [{mark}] {item['text']}")
        atts = n.get("attachments") or []
        if atts:
            print("attachments:")
            for a in atts:
                extra = f"  {a.get('url')}" if a.get("url") else ""
                print(f"  - {a.get('name') or a.get('id')}{extra}")
        links = parse_links(n.get("html") or "")
        if links:
            print("links:")
            for link in links[:10]:
                print(f"  {link}")
        print(n.get("body") or "")
        if n.get("truncated"):
            print("\n… truncated. Re-run with --full for the rest.")


def print_search(data):
    idx = data.get("index") or {}
    age = idx.get("ageSeconds")
    age_s = f", index {age}s old" if age is not None else ""
    print(f"query: {data.get('query')}   hits: {data.get('total')}   source: {data.get('source')}{age_s}")
    for n in data.get("notes") or []:
        loc = " / ".join(x for x in (n.get("account"), n.get("path") or n.get("folder")) if x)
        print(f"  [{n.get('match')}] {n.get('title')}  ({loc})")
        if n.get("snippet"):
            print(f"      {n.get('snippet')}")
    if data.get("truncated"):
        print("  … more (raise --limit)")


def print_reindex(data):
    print(f"mode: {data.get('mode')}   notes: {data.get('notes')}   folders: {data.get('folders')}")
    print(f"bodies refreshed: {data.get('bodiesRefreshed')}   unchanged: {data.get('unchanged')}   added: {data.get('added')}   removed: {data.get('removed')}")
    if data.get("dirtyFolders") is not None:
        print(f"dirty folders: {data.get('dirtyFolders')}")
    print(f"seconds: {data.get('seconds')}")
    print(f"cache: {data.get('path')}  (mode 0600, plaintext, this Mac only)")
    if not data.get("includeTrash"):
        print("Recently Deleted is not in the index.")
    warnings = data.get("warnings") or []
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)


def print_status(data):
    if not data.get("exists"):
        print("no index. Run: grok-notes reindex")
        print(f"cache: {data.get('path')}")
        return
    print(f"notes: {data.get('notes')}   folders: {data.get('folders')}")
    print(f"indexed: {data.get('indexedAt')}   age: {data.get('ageSeconds')}s   mode: {data.get('mode')}")
    print(f"cache: {data.get('path')}")


def print_tags(data):
    scope = data.get("folder") or "all folders"
    print(f"hashtags: {data.get('total')}   source: cache   folder: {scope}")
    for t in data.get("tags") or []:
        print(f"  #{t.get('tag')}  ({t.get('count')})")
    if data.get("truncated"):
        print("  … more (raise --limit)")


def print_mutation(data):
    loc = " / ".join(x for x in (data.get("account"), data.get("path") or data.get("folder") or data.get("parent")) if x)
    title = data.get("title") or data.get("name")
    if data.get("deleted") is True and "inRecentlyDeleted" in data:
        where = "permanently deleted" if data.get("permanent") and data.get("deleted") else "moved to Recently Deleted"
        print(f"{where}: {data.get('title')}")
        print(f"id: {data.get('id')}")
        stale_note()
        return
    if data.get("deleted") and data.get("name") and not data.get("title"):
        print(f"deleted folder: {data.get('account') or ''} / {data.get('name')}  (notes that were inside: {data.get('notes')})")
        stale_note()
        return
    if data.get("permanent") and "deleted" in data and "folders" in data:
        print(f"permanently deleted {data.get('deleted')} notes from Recently Deleted")
        stale_note()
        return
    action = "ok"
    for key in ("created", "updated", "moved", "opened", "checklistAdded", "duplicatedFrom"):
        if data.get(key):
            action = key
            break
    print(f"{action}: {title}")
    if loc:
        print(loc)
    if data.get("id"):
        print(f"id: {data.get('id')}")
    if data.get("shared") is not None and data.get("gap"):
        print(f"shared: {data.get('shared')}   folder shared: {data.get('folderShared')}")
        print(data.get("gap"))
    if data.get("attachments") is not None and "gap" not in data and action == "ok":
        atts = data.get("attachments") or []
        print(f"attachments: {len(atts)}")
        for a in atts:
            print(f"  - {a.get('name') or a.get('id')}")
    stale_note()


def print_gaps(_data=None):
    print("What Notes scripting cannot do on this Mac (honest gaps):")
    for g in GAPS:
        print(f"- {g}")
    print("Cache: ~/.cache/grok-notes/index.sqlite holds plaintext so search does not walk Apple Events. It is mode 0600. grok-notes cache-clear deletes the cache only, not the notes.")


def _print_warnings(data):
    for warning in data.get("warnings") or []:
        print(f"warning: {warning}", file=sys.stderr)


def _stat_line(stats):
    stats = stats or {}
    return (
        f"headings: {stats.get('headings', 0)}  "
        f"bullets: {stats.get('bulletItems', 0)}  "
        f"numbered: {stats.get('orderedItems', 0)}"
    )


def print_import_md(data):
    _print_warnings(data)
    if data.get("dryRun"):
        print(f"dry-run: would import {data.get('file')} into Notes.app")
        print(f"title: {data.get('title')}")
        print(f"folder: {data.get('folderLabel')}")
        print(f"account: {data.get('account') or 'default'}")
        print(f"bytes: {data.get('bytes')}  {_stat_line(data.get('stats'))}")
        print("bridge: Notes.app HTML. File > Import Markdown is not in the scripting dictionary.")
        print(data.get("message") or "Pass --force to create the note.")
        return
    loc = " / ".join(x for x in (data.get("account"), data.get("path") or data.get("folder")) if x)
    print(f"imported: {data.get('title')}")
    if loc:
        print(loc)
    if data.get("id"):
        print(f"id: {data.get('id')}")
    print(f"file: {data.get('file')}")
    stale_note()


def print_export_md(data):
    _print_warnings(data)
    if data.get("dryRun"):
        print(f"dry-run: would write {data.get('file')}")
        print(f"title: {data.get('title')}")
        if data.get("id"):
            print(f"id: {data.get('id')}")
        loc = " / ".join(x for x in (data.get("account"), data.get("folder")) if x)
        if loc:
            print(loc)
        print(f"markdown bytes: {data.get('bytes')}  {_stat_line(data.get('stats'))}")
        print("bridge: Notes.app HTML. File > Export To > Markdown is not in the scripting dictionary.")
        if data.get("wouldRefuse"):
            print(data.get("wouldRefuse"))
        print(data.get("message") or "Notes was read and not changed. Pass --force to write the file.")
        return
    print(f"exported: {data.get('title')}")
    if data.get("id"):
        print(f"id: {data.get('id')}")
    print(f"file: {data.get('file')}")
    print(f"bytes: {data.get('bytes')}")



def checklist_backlink(note_id, note_title):
    title = note_title or "(untitled)"
    return f"Backlink\ntitle: {title}\nid: {note_id}"


def promotion_plan(note_id, note_title, line_text, due=None, list_name=None):
    plan = {
        "title": line_text,
        "notes": checklist_backlink(note_id, note_title),
    }
    if due:
        plan["due"] = due
    if list_name:
        plan["list"] = list_name
    return plan


def select_checklist_line(items, index, text):
    items = items or []
    if index is not None and text is not None and str(text).strip():
        return {"ok": False, "error": "bad_request", "message": "Pass --index or --text, not both. Nothing was created."}
    if index is None and not (text and str(text).strip()):
        return {"ok": False, "error": "missing_line", "message": "Pass --index or --text for one checklist line. Nothing was created."}
    if not items:
        return {"ok": False, "error": "no_checklist", "message": "That note has no checklist lines. Nothing was created."}
    if index is not None:
        if index < 1 or index > len(items):
            return {"ok": False, "error": "bad_index", "message": f"Checklist index must be 1 through {len(items)}. Nothing was created."}
        item = items[index - 1]
        return {"ok": True, "text": item["text"], "index": index, "checked": bool(item.get("checked"))}
    needle = str(text).strip()
    hits = [(i, item) for i, item in enumerate(items, 1) if item.get("text") == needle]
    if not hits:
        return {"ok": False, "error": "not_found", "message": "No checklist line with that exact text. Nothing was created."}
    if len(hits) > 1:
        return {"ok": False, "error": "ambiguous", "message": "More than one checklist line has that exact text. Pass --index. Nothing was created."}
    i, item = hits[0]
    return {"ok": True, "text": item["text"], "index": i, "checked": bool(item.get("checked"))}


_REMINDERS = None


def load_reminders_cli():
    """The existing grok-reminders CLI. Not a second reminders backend."""
    global _REMINDERS
    if _REMINDERS is None:
        import importlib.util
        path = Path(__file__).resolve().parents[2] / "grok-reminders" / "lib" / "cli.py"
        spec = importlib.util.spec_from_file_location("grok_reminders_cli", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _REMINDERS = mod
    return _REMINDERS


def apply_reminder(plan):
    reminders = load_reminders_cli()
    payload = reminders.build_add_payload(
        plan["title"],
        list_name=plan.get("list"),
        due=plan.get("due"),
        notes=plan.get("notes"),
    )
    return reminders.call_jxa(payload, reminders.LONG_TIMEOUT, False)


def print_promote(data):
    line = data.get("line")
    if data.get("dryRun"):
        print(f"dry-run: would add one reminder {line!r}")
    else:
        rid = data.get("reminderId") or ""
        print(f"added reminder {line!r}" + (f"  id {rid}" if rid else ""))
    print(f"note: {data.get('noteTitle')}")
    print(f"id: {data.get('noteId')}")
    if data.get("due"):
        print(f"due: {data.get('due')}")
    else:
        print("due: none")
    if data.get("list"):
        print(f"list: {data.get('list')}")
    print("checklist line left unchanged (checked state is not reliable; the backlink is on the reminder)")
    if data.get("message"):
        print(data["message"])


def cmd_promote_checklist(args, as_json):
    note_id = (args.id or "").strip()
    if not note_id:
        die(2, "missing_id", "promote-checklist needs --id. Nothing was created.", as_json)
    line_text = args.text if isinstance(args.text, str) else None
    if args.index is not None and line_text is not None and line_text.strip():
        die(2, "bad_request", "Pass --index or --text, not both. Nothing was created.", as_json)
    if args.index is None and not (line_text and line_text.strip()):
        die(2, "missing_line", "Pass --index or --text for one checklist line. Nothing was created.", as_json)
    due = args.due.strip() if isinstance(args.due, str) and args.due.strip() else None
    if due and not load_reminders_cli()._due_ok(due):
        die(2, "bad_request", "Due must be YYYY-MM-DD or YYYY-MM-DD HH:MM. Notes and Reminders were not called.", as_json)
    list_name = args.list.strip() if isinstance(args.list, str) and args.list.strip() else None
    data = call_jxa({"cmd": "show", "id": note_id, "full": True}, 60, as_json)
    if not data.get("ok"):
        emit(data, as_json, print_promote)
        return 0
    notes = data.get("notes") or []
    if not notes:
        die(1, "not_found", "No note with that id. Nothing was created.", as_json)
    if len(notes) != 1:
        die(2, "ambiguous", "More than one note matched that id. Nothing was created.", as_json)
    note = notes[0]
    if note.get("locked"):
        die(1, "locked", "Note is password protected. Nothing was created.", as_json)
    chosen = select_checklist_line(parse_checklist(note.get("html") or ""), args.index, line_text)
    if not chosen.get("ok"):
        die(2, chosen.get("error") or "bad_request", chosen.get("message") or "Nothing was created.", as_json)
    plan = promotion_plan(note.get("id") or note_id, note.get("title"), chosen["text"], due=due, list_name=list_name)
    summary = {
        "ok": True,
        "tool": "grok-notes",
        "version": VERSION,
        "command": "promote-checklist",
        "dryRun": not args.force,
        "applied": False,
        "checklistChanged": False,
        "noteId": note.get("id") or note_id,
        "noteTitle": note.get("title"),
        "index": chosen["index"],
        "line": chosen["text"],
        "checked": chosen["checked"],
        "due": due,
        "list": list_name,
        "reminder": plan,
        "bridge": "grok-reminders-add",
    }
    if not args.force:
        summary["message"] = "dry-run: Notes was only read. Reminders.app was not called. Pass --force to add one reminder. The checklist line is not marked done."
        emit(summary, as_json, print_promote)
        return 0
    created = apply_reminder(plan)
    if not created.get("ok"):
        emit(created, as_json, print_promote)
        return 0
    summary["dryRun"] = False
    summary["applied"] = True
    summary["reminderId"] = created.get("id")
    summary["reminderList"] = created.get("list")
    summary["message"] = "Added one reminder through grok-reminders. The checklist line was not changed."
    emit(summary, as_json, print_promote)
    return 0


def add_target(p):
    p.add_argument("title", nargs="?", help="exact note title")
    p.add_argument("--title", dest="title_flag", help="exact note title")
    p.add_argument("--id", help="note id")
    p.add_argument("--folder")
    p.add_argument("--account")
    p.add_argument("--parent")


def build_parser():
    parent = argparse.ArgumentParser(add_help=False)
    parent.add_argument("--json", action="store_true")
    parser = argparse.ArgumentParser(
        prog="grok-notes",
        description="Apple Notes CLI via Notes.app (interim, not MacStories NotesCTL). Search uses a local cache.",
        parents=[parent],
    )
    parser.add_argument("--version", action="version", version=f"grok-notes {VERSION}")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("doctor", parents=[parent], help="check Automation and the index")
    p = sub.add_parser("gaps", parents=[parent], help="what this CLI cannot do")
    p = sub.add_parser("folders", parents=[parent], help="folder tree")
    p.add_argument("--cached", action="store_true", help="use the last reindex instead of Notes.app")
    p = sub.add_parser("list", parents=[parent], help="list notes in a folder")
    p.add_argument("folder", nargs="?")
    p.add_argument("--folder")
    p.add_argument("--account")
    p.add_argument("--parent")
    p.add_argument("--limit", type=int)
    p = sub.add_parser("show", parents=[parent], help="show one note")
    add_target(p)
    p.add_argument("--limit", type=int)
    p.add_argument("--full", action="store_true")
    p = sub.add_parser("search", parents=[parent], help="search the cache (or --live)")
    p.add_argument("query")
    p.add_argument("--folder")
    p.add_argument("--account")
    p.add_argument("--limit", type=int)
    p.add_argument("--live", action="store_true", help="Apple Event search, slow")
    p.add_argument("--include-trash", action="store_true")
    p = sub.add_parser("reindex", parents=[parent], help="refresh the local search index")
    p.add_argument("--full", action="store_true", help="reread every note body")
    p.add_argument("--include-trash", action="store_true")
    sub.add_parser("status", parents=[parent], help="index age and counts")
    p = sub.add_parser("cache-clear", parents=[parent], help="delete the local index only")
    p = sub.add_parser("tags", parents=[parent], help="hashtags from the index (no Apple Event)")
    p.add_argument("--limit", type=int)
    p.add_argument("--folder", help="Only notes in this folder name or path")
    p = sub.add_parser("create-note", parents=[parent])
    p.add_argument("--title", required=True)
    p.add_argument("--body")
    p.add_argument("--html")
    p.add_argument("--folder")
    p.add_argument("--account")
    p.add_argument("--parent")
    p = sub.add_parser("create-folder", parents=[parent])
    p.add_argument("name")
    p.add_argument("--account")
    p.add_argument("--parent")
    p = sub.add_parser("rename-folder", parents=[parent])
    p.add_argument("name")
    p.add_argument("new_name")
    p.add_argument("--account")
    p.add_argument("--parent")
    p = sub.add_parser("delete-folder", parents=[parent])
    p.add_argument("name")
    p.add_argument("--account")
    p.add_argument("--parent")
    p.add_argument("--force", action="store_true")
    p.add_argument("--allow-large", action="store_true")
    p = sub.add_parser("edit", parents=[parent])
    add_target(p)
    p.add_argument("--body")
    p.add_argument("--html")
    p.add_argument("--append")
    p.add_argument("--rename")
    p = sub.add_parser("append", parents=[parent])
    add_target(p)
    p.add_argument("--text", required=True)
    p = sub.add_parser("move", parents=[parent])
    add_target(p)
    p.add_argument("--to-folder", required=True)
    p.add_argument("--to-account")
    p.add_argument("--to-parent")
    p = sub.add_parser("duplicate", parents=[parent])
    add_target(p)
    p.add_argument("--to-folder")
    p.add_argument("--to-account")
    p.add_argument("--to-parent")
    p = sub.add_parser("delete-note", parents=[parent])
    add_target(p)
    p.add_argument("--force", action="store_true")
    p.add_argument("--permanent", action="store_true")
    p = sub.add_parser("empty-trash", parents=[parent])
    p.add_argument("--force", action="store_true")
    p.add_argument("--account")
    p = sub.add_parser("attachments", parents=[parent])
    add_target(p)
    chk = sub.add_parser("checklist", parents=[parent])
    chk_sub = chk.add_subparsers(dest="checklist_cmd")
    s = chk_sub.add_parser("show", parents=[parent])
    add_target(s)
    s.add_argument("--full", action="store_true")
    s = chk_sub.add_parser("add", parents=[parent])
    add_target(s)
    s.add_argument("--text", required=True)

    p = sub.add_parser("promote-checklist", parents=[parent], help="turn one checklist line into one reminder (dry-run unless --force)")
    p.add_argument("--id", help="note id")
    p.add_argument("--index", type=int, help="1-based checklist line")
    p.add_argument("--text", help="exact checklist line text")
    p.add_argument("--due", help="YYYY-MM-DD or YYYY-MM-DD HH:MM; omit for no due date")
    p.add_argument("--list", help="Reminders list name")
    p.add_argument("--force", action="store_true", help="add the reminder through grok-reminders; without this, Notes is only read")
    p = sub.add_parser("share", parents=[parent])
    add_target(p)
    for name in ("pin", "unpin", "lock", "unlock"):
        p = sub.add_parser(name, parents=[parent])
        add_target(p)
    p = sub.add_parser("open", parents=[parent], help="reveal the note in Notes (focuses the app)")
    add_target(p)
    p = sub.add_parser("import-md", parents=[parent], help="import a markdown file into Notes (dry-run unless --force)")
    p.add_argument("path", help="markdown file to import")
    p.add_argument("--title", help="note title; default is the first heading or the file name")
    p.add_argument("--folder")
    p.add_argument("--account")
    p.add_argument("--parent")
    p.add_argument("--force", action="store_true", help="create the note; without this, Notes is not called")
    p = sub.add_parser("export-md", parents=[parent], help="export one note to a markdown file (dry-run unless --force)")
    add_target(p)
    p.add_argument("--out", required=True, help="markdown file to write")
    p.add_argument("--force", action="store_true", help="write --out; without this, the note is only read")
    p.add_argument("--replace", action="store_true", help="overwrite --out if it already exists")
    return parser


def cmd_import_md(args, as_json):
    path = Path(args.path).expanduser()
    if not path.is_file():
        die(2, "missing_path", f"No markdown file at {path}", as_json)
    if path.stat().st_size > 400_000:
        die(2, "too_large", "Markdown file is over 400000 bytes.", as_json)
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        die(2, "bad_encoding", "Markdown file is not UTF-8.", as_json)
    converted = markdown_notes.markdown_to_notes_html(text, title=args.title, fallback_title=path.stem)
    if not converted.get("ok"):
        die(2, converted.get("error") or "bad_markdown", converted.get("message") or "Could not read that markdown.", as_json)
    summary = {
        "ok": True,
        "tool": "grok-notes",
        "version": VERSION,
        "command": "import-md",
        "dryRun": not args.force,
        "file": str(path.resolve()),
        "title": converted["title"],
        "folder": args.folder,
        "folderLabel": args.folder or "account default",
        "account": args.account,
        "parent": args.parent,
        "bytes": len(text.encode("utf-8")),
        "stats": converted.get("stats") or {},
        "warnings": converted.get("warnings") or [],
        "bridge": "notes-html",
    }
    if not args.force:
        summary["message"] = "Notes.app was not called. Pass --force to create the note."
        emit(summary, as_json, print_import_md)
        return 0
    data = call_jxa(
        {
            "cmd": "import-md",
            "title": converted["title"],
            "html": converted["html"],
            "force": True,
            "folder": args.folder,
            "account": args.account,
            "parent": args.parent,
        },
        90,
        as_json,
    )
    if data.get("ok"):
        data.update({
            "tool": "grok-notes",
            "version": VERSION,
            "command": "import-md",
            "dryRun": False,
            "file": summary["file"],
            "warnings": summary["warnings"],
            "stats": summary["stats"],
            "bridge": "notes-html",
        })
    emit(data, as_json, print_import_md)
    return 0


def cmd_export_md(args, as_json):
    out = Path(args.out).expanduser()
    if not str(args.out).strip():
        die(2, "missing_out", "export-md needs --out.", as_json)
    if out.exists() and out.is_dir():
        die(2, "file_exists", f"{out} is a directory.", as_json)
    if out.parent and not out.parent.is_dir():
        die(2, "missing_path", f"Directory does not exist: {out.parent}", as_json)
    title = getattr(args, "title_flag", None) or getattr(args, "title", None)
    if not getattr(args, "id", None) and not title:
        die(2, "missing_target", "export-md needs --id or a title.", as_json)
    payload = target_payload(args, "show")
    payload["full"] = True
    data = call_jxa(payload, 90, as_json)
    if not data.get("ok"):
        emit(data, as_json, print_export_md)
        return 0
    notes = data.get("notes") or []
    if not notes:
        die(1, "not_found", "No note with that exact title or id.", as_json)
    note = notes[0]
    if note.get("locked"):
        die(1, "locked", "Note is password protected. export-md does not read it.", as_json)
    converted = markdown_notes.notes_html_to_markdown(note.get("html") or "", title=note.get("title"))
    warnings = list(converted.get("warnings") or [])
    named = [a.get("name") for a in (note.get("attachments") or []) if a.get("name")]
    if named:
        warnings.append("Omitted attachments: " + ", ".join(named) + ". Drawings, scans, and files are not written into the markdown.")
    markdown = converted.get("markdown") or ""
    exists = out.exists()
    summary = {
        "ok": True,
        "tool": "grok-notes",
        "version": VERSION,
        "command": "export-md",
        "dryRun": not args.force,
        "file": str(out.resolve()),
        "title": note.get("title"),
        "id": note.get("id"),
        "account": note.get("account"),
        "folder": note.get("folder"),
        "path": note.get("path"),
        "bytes": len(markdown.encode("utf-8")),
        "stats": converted.get("stats") or {},
        "warnings": warnings,
        "bridge": "notes-html",
    }
    if exists and not args.replace:
        summary["wouldRefuse"] = f"{out} already exists. Pass --replace with --force to overwrite it."
    if not args.force:
        summary["message"] = "Notes was read and not changed. Pass --force to write the file."
        emit(summary, as_json, print_export_md)
        return 0
    if exists and not args.replace:
        die(2, "file_exists", f"{out} already exists. Pass --replace to overwrite it.", as_json)
    tmp = out.with_name(out.name + ".grok-notes-tmp")
    try:
        tmp.write_text(markdown, encoding="utf-8")
        tmp.replace(out)
    except OSError as exc:
        try:
            tmp.unlink()
        except OSError:
            pass
        die(1, "write_failed", str(exc), as_json)
    emit(summary, as_json, print_export_md)
    return 0


def target_payload(args, cmd):
    payload = {"cmd": cmd}
    if getattr(args, "id", None):
        payload["id"] = args.id
    title = getattr(args, "title_flag", None) or getattr(args, "title", None)
    if title:
        payload["title"] = title
    if getattr(args, "folder", None):
        payload["folder"] = args.folder
    if getattr(args, "account", None):
        payload["account"] = args.account
    if getattr(args, "parent", None):
        payload["parent"] = args.parent
    return payload


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    as_json = bool(getattr(args, "json", False))
    if not args.cmd:
        parser.print_help()
        return 2
    sys.path.insert(0, str(LIB.parent))

    if args.cmd == "gaps":
        data = {"ok": True, "gaps": GAPS}
        emit(data, as_json, print_gaps)
        return 0
    if args.cmd == "status":
        emit(indexlib.status(), as_json, print_status)
        return 0
    if args.cmd == "cache-clear":
        data = indexlib.clear_cache()
        emit(data, as_json, lambda d: print(f"removed cache files: {', '.join(d.get('removed') or []) or '(none)'}"))
        return 0
    if args.cmd == "tags":
        data = indexlib.list_tags(args.limit or 50, folder=args.folder)
        emit(data, as_json, print_tags)
        return 0
    if args.cmd == "search" and not args.live:
        data = indexlib.search(args.query, limit=args.limit or 20, folder=args.folder, account=args.account)
        emit(data, as_json, print_search)
        return 0
    if args.cmd == "reindex":
        def jxa(payload, timeout=180):
            return call_jxa(payload, timeout, as_json)
        if not as_json:
            print("indexing via Notes.app…", file=sys.stderr)
        data = indexlib.reindex(jxa, full=args.full, include_trash=args.include_trash)
        emit(data, as_json, print_reindex)
        return 0
    if args.cmd == "folders" and args.cached:
        data = indexlib.cached_folders()
        emit(data, as_json, print_folders)
        return 0
    if args.cmd == "promote-checklist":
        return cmd_promote_checklist(args, as_json)
    if args.cmd == "import-md":
        return cmd_import_md(args, as_json)
    if args.cmd == "export-md":
        return cmd_export_md(args, as_json)

    payload = {"cmd": args.cmd}
    timeout = 60
    mutating = False
    if args.cmd == "doctor":
        timeout = 45
    elif args.cmd == "folders":
        payload = {"cmd": "folders"}
        timeout = 90
    elif args.cmd == "list":
        folder = args.folder or args.folder_name if hasattr(args, "folder_name") else args.folder
        # positional folder is args.folder only if --folder wasn't used as dest clash
        folder = getattr(args, "folder", None) or "Notes"
        # argparse: positional "folder" and optional --folder share... I used both.
        # The positional is stored as folder if I named it folder, and --folder overwrites.
        # I added both p.add_argument("folder") and p.add_argument("--folder") which CONFLICT.
        payload = {"cmd": "list", "folder": args.folder or "Notes"}
        if args.account:
            payload["account"] = args.account
        if args.parent:
            payload["parent"] = args.parent
        if args.limit:
            payload["limit"] = args.limit
        timeout = 90
    elif args.cmd == "show":
        payload = target_payload(args, "show")
        if args.full:
            payload["full"] = True
        if args.limit:
            payload["bodyLimit"] = args.limit
        timeout = 60
    elif args.cmd == "search":
        payload = {"cmd": "search", "query": args.query, "includeTrash": args.include_trash}
        if args.folder:
            payload["folder"] = args.folder
        if args.account:
            payload["account"] = args.account
        if args.limit:
            payload["limit"] = args.limit
        timeout = 120
    elif args.cmd == "create-note":
        payload = {"cmd": "create-note", "title": args.title, "body": args.body, "html": args.html, "folder": args.folder, "account": args.account, "parent": args.parent}
        mutating = True
    elif args.cmd == "create-folder":
        payload = {"cmd": "create-folder", "name": args.name, "account": args.account, "parent": args.parent}
        mutating = True
    elif args.cmd == "rename-folder":
        payload = {"cmd": "rename-folder", "name": args.name, "newName": args.new_name, "account": args.account, "parent": args.parent}
        mutating = True
    elif args.cmd == "delete-folder":
        payload = {"cmd": "delete-folder", "name": args.name, "account": args.account, "parent": args.parent, "force": args.force, "allowLarge": args.allow_large}
        mutating = True
        timeout = 90
    elif args.cmd == "edit":
        payload = target_payload(args, "edit")
        payload.update({"body": args.body, "html": args.html, "append": args.append, "rename": args.rename})
        mutating = True
    elif args.cmd == "append":
        payload = target_payload(args, "edit")
        payload["append"] = args.text
        mutating = True
    elif args.cmd == "move":
        payload = target_payload(args, "move")
        payload.update({"toFolder": args.to_folder, "toAccount": args.to_account, "toParent": args.to_parent})
        mutating = True
    elif args.cmd == "duplicate":
        payload = target_payload(args, "duplicate")
        payload.update({"toFolder": args.to_folder, "toAccount": args.to_account, "toParent": args.to_parent})
        mutating = True
    elif args.cmd == "delete-note":
        payload = target_payload(args, "delete-note")
        payload.update({"force": args.force, "permanent": args.permanent})
        mutating = True
        timeout = 90
    elif args.cmd == "empty-trash":
        payload = {"cmd": "empty-trash", "force": args.force, "account": args.account}
        mutating = True
        timeout = 180
    elif args.cmd == "attachments":
        payload = target_payload(args, "attachments")
    elif args.cmd == "checklist":
        if args.checklist_cmd == "add":
            payload = target_payload(args, "checklist-add")
            payload["text"] = args.text
            mutating = True
        else:
            payload = target_payload(args, "show")
            payload["full"] = True
            if as_json:
                data = call_jxa(payload, 60, as_json)
                if data.get("ok"):
                    for n in data.get("notes") or []:
                        n["checklist"] = parse_checklist(n.get("html") or "")
                emit(data, True, print_show)
                return 0
    elif args.cmd == "share":
        payload = target_payload(args, "share")
    elif args.cmd in ("pin", "unpin", "lock", "unlock"):
        payload = {"cmd": args.cmd}
    elif args.cmd == "open":
        payload = target_payload(args, "open")
        mutating = False
    else:
        die(2, "unknown_command", args.cmd, as_json)

    data = call_jxa(payload, timeout, as_json)
    if args.cmd == "doctor" and data.get("ok"):
        data["index"] = indexlib.status()
        data["version"] = VERSION
    if args.cmd == "show" and data.get("ok"):
        for n in data.get("notes") or []:
            n["checklist"] = parse_checklist(n.get("html") or "")
            n["links"] = parse_links(n.get("html") or "")
    if args.cmd == "checklist" and args.checklist_cmd != "add" and data.get("ok"):
        for n in data.get("notes") or []:
            n["checklist"] = parse_checklist(n.get("html") or "")

    printers = {
        "doctor": print_doctor,
        "folders": print_folders,
        "list": print_list,
        "show": print_show,
        "search": print_search,
        "checklist": print_show,
    }
    printer = printers.get(args.cmd, print_mutation)
    if mutating and data.get("ok") and not as_json:
        pass
    emit(data, as_json, printer)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BrokenPipeError:
        raise SystemExit(0)
