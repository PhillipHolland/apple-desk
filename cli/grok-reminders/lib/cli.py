#!/usr/bin/env python3
"""grok-reminders command line. Reminders.app via JXA. Not RemCTL."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

VERSION = "0.1.2"
LIB = Path(__file__).resolve().parent / "reminders.js"

GAPS = [
    "This is Reminders.app scripting, not RemCTL and not EventKit. RemCTL may still be installed on this Mac. Do not call it for Apple Desk work.",
    "No smart lists, sections, tags, subtasks, recurrence, location alarms, early reminders, or URLs. Flag is read-only. There is no move between lists.",
    "Sharing is out. You cannot invite someone or see sharees.",
    "Due times are this Mac's local timezone. Pass YYYY-MM-DD or YYYY-MM-DD HH:MM. A date with no time is stored at 09:00 local.",
    "today is incomplete reminders whose due day is today. upcoming is incomplete reminders due from today through N days (default 7). Reminders with no due date are in neither.",
    "search matches title and notes, case-insensitive, incomplete only unless --include-completed. It refuses queries shorter than 2 characters and returns at most 40 hits.",
    "delete removes one reminder and refuses without --force. There is no delete-all and no Recently Deleted recovery.",
    "Very large lists are read in bulk per list and capped at 4000 reminders per collect. A list the app will not script is skipped with an error rather than retried.",
    "Automation for Grok Bot (or Grok Bot Helper) to control Reminders is required. If that dialog is waiting, stop. Do not loop doctor.",
]

AUTH_HINT = (
    "If a dialog is on screen: Grok Bot wants access to control Reminders. Click Allow once when you are back.\n"
    "If it is gone: System Settings → Privacy & Security → Automation → Grok Bot (and Grok Bot Helper) → Reminders on.\n"
    "Do not toggle repeatedly. One change, then run doctor again. Do not retry doctor in a loop while AFK. This CLI does not use RemCTL."
)

DOCTOR_TIMEOUT = 20
DEFAULT_TIMEOUT = 20
LONG_TIMEOUT = 25


def die(code, error, message, as_json):
    authish = error in ("automation_denied", "automation_timeout")
    payload = {
        "ok": False,
        "tool": "grok-reminders",
        "version": VERSION,
        "error": error,
        "code": code,
        "message": message,
    }
    if authish:
        payload["hint"] = AUTH_HINT
        payload["settings"] = AUTH_HINT
    if as_json:
        print(json.dumps(payload))
    else:
        print(f"grok-reminders: {error}", file=sys.stderr)
        if message:
            print(message, file=sys.stderr)
        if authish:
            print(AUTH_HINT, file=sys.stderr)
    raise SystemExit(code)


def call_jxa(payload, timeout, as_json):
    proc = subprocess.run(
        ["perl", "-e", "alarm shift @ARGV; exec @ARGV", str(timeout), "osascript", "-l", "JavaScript", str(LIB), "--", json.dumps(payload)],
        capture_output=True,
        text=True,
    )
    blob = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
    if proc.returncode in (-14, 142) or "Alarm clock" in blob:
        die(4, "automation_timeout", f"Timed out after {timeout}s waiting for Reminders. A permission dialog may be waiting. Stop; do not retry in a loop.", as_json)
    if proc.returncode != 0:
        if "-1743" in blob or "Not authorized to send Apple events" in blob:
            die(3, "automation_denied", blob, as_json)
        if "-1712" in blob or "timed out" in blob.lower():
            die(4, "automation_timeout", blob, as_json)
        die(1, "reminders_error", blob or "osascript failed", as_json)
    raw = (proc.stdout or "").strip()
    if not raw:
        die(1, "reminders_error", "Reminders returned an empty response", as_json)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        die(1, "reminders_error", "Reminders returned non-JSON: " + raw[:400], as_json)
    if data.get("error") == "automation_denied":
        die(3, "automation_denied", data.get("message") or "", as_json)
    if data.get("error") == "automation_timeout":
        die(4, "automation_timeout", (data.get("message") or "") + " Stop; do not retry in a loop.", as_json)
    return data


def emit(data, as_json, text_fn):
    if not data.get("ok", False):
        soft = {
            "needs_force", "missing_title", "missing_id", "missing_query",
            "ambiguous", "bad_request", "not_found", "query_too_broad",
        }
        code = 2 if data.get("error") in soft else 1
        if data.get("error") == "automation_denied":
            code = 3
        if data.get("error") == "automation_timeout":
            code = 4
        if as_json:
            data.setdefault("tool", "grok-reminders")
            data.setdefault("version", VERSION)
            data.setdefault("code", code)
            if data.get("error") in ("automation_denied", "automation_timeout"):
                data.setdefault("hint", AUTH_HINT)
            print(json.dumps(data))
        else:
            print(f"grok-reminders: {data.get('error')}: {data.get('message', '')}", file=sys.stderr)
            if data.get("error") in ("automation_denied", "automation_timeout"):
                print(AUTH_HINT, file=sys.stderr)
        raise SystemExit(code)
    if as_json:
        data.setdefault("tool", "grok-reminders")
        data.setdefault("version", VERSION)
        print(json.dumps(data))
    else:
        text_fn(data)


def cmd_doctor(args):
    as_json = args.json
    script = call_jxa({"op": "doctor"}, DOCTOR_TIMEOUT, as_json)
    if not script.get("ok", True) and script.get("error"):
        emit(script, as_json, lambda d: None)
    data = {
        "ok": True,
        "automation": "authorized",
        "backend": "reminders-app-jxa",
        "readOnly": False,
        "deleteRequiresForce": True,
        "remindersApp": {"name": script.get("name"), "version": script.get("version")},
        "lists": script.get("lists"),
        "reminders": script.get("reminders"),
        "incomplete": script.get("incomplete"),
        "defaultList": script.get("defaultList"),
    }

    def text(d):
        app = d["remindersApp"]
        print(f"grok-reminders {VERSION}  ok")
        print(f"Reminders {app.get('version')}  lists {d.get('lists')}  reminders {d.get('reminders')}  incomplete {d.get('incomplete')}")
        print(f"default list: {d.get('defaultList')}")
        print(f"automation: {d['automation']}")
        print("backend: Reminders.app JXA (not RemCTL)")
        print("writes: add and done are live; delete needs --force")

    emit(data, as_json, text)


def cmd_lists(args):
    as_json = args.json
    data = call_jxa({"op": "lists"}, DEFAULT_TIMEOUT, as_json)

    def text(d):
        print(f"{d.get('count')} lists")
        for row in d.get("lists") or []:
            print(f"{row.get('incomplete', 0):4} open  {row.get('reminders', 0):4} total  {row.get('name')}")

    emit(data, as_json, text)


def _collect(as_json, list_name, with_body):
    return call_jxa({
        "op": "collect",
        "list": list_name,
        "withBody": with_body,
        "cap": 4000,
    }, LONG_TIMEOUT, as_json)


def _today_key():
    return datetime.now().strftime("%Y-%m-%d")


def _print_rows(rows):
    for row in rows:
        due = row.get("due") or "-"
        flag = " !" if row.get("flagged") else ""
        print(f"{due:19}  {row.get('priority', 'none'):6}  {row.get('list') or '-':16}  {row.get('title')}{flag}")


def cmd_today(args):
    as_json = args.json
    data = _collect(as_json, args.list, False)
    if not data.get("ok"):
        emit(data, as_json, lambda d: None)
    today = _today_key()
    rows = [r for r in data.get("reminders") or [] if not r.get("completed") and r.get("due") and r["due"][:10] == today]
    out = {"ok": True, "day": today, "count": len(rows), "reminders": rows, "truncated": data.get("truncated")}

    def text(d):
        print(f"{d['count']} due {d['day']}")
        _print_rows(d["reminders"])

    emit(out, as_json, text)


def cmd_upcoming(args):
    as_json = args.json
    data = _collect(as_json, args.list, False)
    if not data.get("ok"):
        emit(data, as_json, lambda d: None)
    start = _today_key()
    end_ord = datetime.strptime(start, "%Y-%m-%d").toordinal() + args.days - 1
    end = datetime.fromordinal(end_ord).strftime("%Y-%m-%d")
    rows = []
    for row in data.get("reminders") or []:
        if row.get("completed") or not row.get("due"):
            continue
        day = row["due"][:10]
        if start <= day <= end:
            rows.append(row)
    rows.sort(key=lambda r: r.get("due") or "")
    out = {"ok": True, "from": start, "to": end, "days": args.days, "count": len(rows), "reminders": rows, "truncated": data.get("truncated")}

    def text(d):
        print(f"{d['count']} due {d['from']} through {d['to']}")
        _print_rows(d["reminders"])

    emit(out, as_json, text)


def cmd_search(args):
    as_json = args.json
    query = (args.query or "").strip()
    if len(query) < 2:
        die(2, "missing_query", "Search needs at least 2 characters.", as_json)
    data = _collect(as_json, args.list, True)
    if not data.get("ok"):
        emit(data, as_json, lambda d: None)
    needle = query.casefold()
    hits = []
    for row in data.get("reminders") or []:
        if row.get("completed") and not args.include_completed:
            continue
        title = row.get("title") or ""
        body = row.get("body") or ""
        if needle in title.casefold() or needle in body.casefold():
            item = dict(row)
            if body and needle in body.casefold():
                item["snippet"] = " ".join(body.split())[:180]
            item.pop("body", None)
            hits.append(item)
            if len(hits) >= 40:
                break
    out = {"ok": True, "query": query, "count": len(hits), "reminders": hits, "truncated": data.get("truncated")}

    def text(d):
        print(f"{d['count']} matches")
        _print_rows(d["reminders"])

    emit(out, as_json, text)


def cmd_show(args):
    as_json = args.json
    if not args.id:
        die(2, "missing_id", "Pass --id.", as_json)
    data = call_jxa({"op": "show", "id": args.id}, LONG_TIMEOUT, as_json)
    emit(data, as_json, lambda d: print(json.dumps(d.get("reminder"), indent=2)))


def _due_ok(value):
    import re
    return bool(re.fullmatch(r"\d{4}-\d{2}-\d{2}( \d{2}:\d{2})?", value.strip()))

def cmd_add(args):
    as_json = args.json
    title = (args.title or "").strip()
    if not title:
        die(2, "missing_title", "Pass --title. Nothing was added.", as_json)
    if args.due and not _due_ok(args.due):
        die(2, "bad_request", "Due must be YYYY-MM-DD or YYYY-MM-DD HH:MM. Reminders was not called.", as_json)
    if args.dry_run:
        data = {
            "ok": True,
            "dryRun": True,
            "wouldAdd": True,
            "title": title,
            "list": args.list,
            "due": args.due,
            "priority": args.priority,
            "message": "dry-run: Reminders.app was not called.",
        }
        emit(data, as_json, lambda d: print(f"dry-run add {d.get('title')!r} (Reminders not called)"))
        return
    payload = {"op": "add", "title": title}
    if args.list:
        payload["list"] = args.list
    if args.due:
        payload["due"] = args.due
    if args.notes:
        payload["notes"] = args.notes
    if args.priority:
        payload["priority"] = args.priority
    data = call_jxa(payload, LONG_TIMEOUT, as_json)

    def text(d):
        print(f"added {d.get('title')!r} to {d.get('list')}  id {d.get('id')}")

    emit(data, as_json, text)


def cmd_done(args):
    as_json = args.json
    if not args.id:
        die(2, "missing_id", "Pass --id. Nothing was changed.", as_json)
    data = call_jxa({"op": "done", "id": args.id}, LONG_TIMEOUT, as_json)
    emit(data, as_json, lambda d: print(f"completed {d.get('id')}"))


def cmd_delete(args):
    as_json = args.json
    if not args.id:
        die(2, "missing_id", "Pass --id. Nothing was deleted.", as_json)
    if not args.force:
        die(2, "needs_force", "Refusing to delete without --force. One --id only; there is no mass delete. Nothing was deleted.", as_json)
    data = call_jxa({"op": "delete", "id": args.id}, LONG_TIMEOUT, as_json)
    emit(data, as_json, lambda d: print(f"deleted {d.get('id')}"))


def cmd_gaps(args):
    as_json = getattr(args, "json", False)
    data = {"ok": True, "tool": "grok-reminders", "version": VERSION, "gaps": GAPS}
    if as_json:
        print(json.dumps(data))
        return
    print("grok-reminders gaps")
    for item in GAPS:
        print(f"- {item}")


def build_parser():
    parser = argparse.ArgumentParser(prog="grok-reminders", description="Local Apple Reminders CLI (not RemCTL)")
    parser.add_argument("--version", action="version", version=f"grok-reminders {VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_json(p):
        p.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor")
    add_json(doctor)
    doctor.set_defaults(func=cmd_doctor)

    lists = sub.add_parser("lists")
    add_json(lists)
    lists.set_defaults(func=cmd_lists)

    today = sub.add_parser("today")
    add_json(today)
    today.add_argument("--list")
    today.set_defaults(func=cmd_today)

    upcoming = sub.add_parser("upcoming")
    add_json(upcoming)
    upcoming.add_argument("--days", type=int, default=7)
    upcoming.add_argument("--list")
    upcoming.set_defaults(func=cmd_upcoming)

    search = sub.add_parser("search")
    add_json(search)
    search.add_argument("query")
    search.add_argument("--list")
    search.add_argument("--include-completed", action="store_true")
    search.set_defaults(func=cmd_search)

    show = sub.add_parser("show")
    add_json(show)
    show.add_argument("--id", required=True)
    show.set_defaults(func=cmd_show)

    add = sub.add_parser("add")
    add_json(add)
    add.add_argument("--title", required=True)
    add.add_argument("--list")
    add.add_argument("--due", help="YYYY-MM-DD or YYYY-MM-DD HH:MM, Mac local time")
    add.add_argument("--notes")
    add.add_argument("--priority", choices=("high", "medium", "low", "none"))
    add.add_argument("--dry-run", action="store_true", help="Validate only; do not call Reminders.app")
    add.set_defaults(func=cmd_add)

    done = sub.add_parser("done")
    add_json(done)
    done.add_argument("--id", required=True)
    done.set_defaults(func=cmd_done)

    delete = sub.add_parser("delete")
    add_json(delete)
    delete.add_argument("--id", required=True)
    delete.add_argument("--force", action="store_true")
    delete.set_defaults(func=cmd_delete)

    gaps = sub.add_parser("gaps")
    add_json(gaps)
    gaps.set_defaults(func=cmd_gaps)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    days = getattr(args, "days", None)
    if isinstance(days, int) and not 1 <= days <= 60:
        die(2, "bad_request", "--days must be 1 through 60.", getattr(args, "json", False))
    try:
        args.func(args)
    except BrokenPipeError:
        raise SystemExit(0)


if __name__ == "__main__":
    main()
