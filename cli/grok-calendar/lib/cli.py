#!/usr/bin/env python3
"""grok-calendar command line. Calendar.app via JXA. Not a cloud calendar API."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

VERSION = "0.1.1"
LIB = Path(__file__).resolve().parent / "calendar.js"

GAPS = [
    "Direct EventKit is not used. A command-line binary has no NSCalendarsUsageDescription, so macOS often will not show the Calendars privacy prompt for the binary. This CLI asks Calendar.app over Apple Events. The usual grant is Automation (Grok Bot or Grok Bot Helper → Calendar). If Calendar still refuses the data, also enable Grok Bot and Grok Bot Helper under Privacy & Security → Calendars, then quit and reopen Grok Bot.",
    "Reads are the default. create, update, and delete are the only mutations. delete removes one event and refuses without --force. There is no delete-all.",
    "No attendees, invites, RSVP, or proposing a new time. No alarms, travel time, attachments, or availability (busy/free).",
    "Recurrence is read-only on show (the stored rule string). This CLI does not create or edit a series, and it does not target one occurrence versus the whole series.",
    "Events cannot be moved between calendars. update changes fields on the event's current calendar only.",
    "Subscribed and read-only calendars (holidays, birthdays, some shared calendars) can be listed but not written.",
    "list and search stay inside a date window (list defaults to today through 7 days; search defaults to 30 days ago through 180 days ahead). They match title and location only, not notes. A calendar with more than 800 overlapping events in the window is refused.",
    "show, update, and delete look up one uid by scanning calendars. That can be slow on large accounts.",
    "Google, Exchange, and iCloud calendars appear only when they are already in Calendar.app. This is not the Google Calendar connector and not iCloud.com.",
    "Focus filters, widgets, notifications, and conference-link parsing are out of scope. url is returned on show when Calendar exposes it.",
]

AUTH_HINT = (
    "If a dialog is on screen: “Grok Bot” wants access to control “Calendar”. Click Allow once.\n"
    "If it is gone, or Automation was denied: System Settings → Privacy & Security → Automation → Grok Bot (and Grok Bot Helper) → turn Calendar on.\n"
    "If Calendar still will not list events: System Settings → Privacy & Security → Calendars → enable Grok Bot and Grok Bot Helper, then quit and reopen Grok Bot.\n"
    "Do not toggle repeatedly. One change, then run doctor again. Do not retry doctor in a loop while AFK."
)

# Hard cap for every Apple Event call. Prefer 20s; never hang 60s+.
DOCTOR_TIMEOUT = 20
DEFAULT_TIMEOUT = 20
LONG_TIMEOUT = 25


def die(code, error, message, as_json):
    authish = error in ("automation_denied", "automation_timeout", "calendar_tcc")
    payload = {
        "ok": False,
        "tool": "grok-calendar",
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
        print(f"grok-calendar: {error}", file=sys.stderr)
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
        die(4, "automation_timeout", f"Timed out after {timeout}s waiting for Calendar. A permission dialog may be waiting. Stop; do not retry in a loop.", as_json)
    if proc.returncode != 0:
        if "kTCCServiceCalendar" in blob or "Calendar access" in blob:
            die(3, "calendar_tcc", blob, as_json)
        if "-1743" in blob or "Not authorized to send Apple events" in blob:
            die(3, "automation_denied", blob, as_json)
        if "-1712" in blob or "timed out" in blob.lower():
            die(4, "automation_timeout", blob, as_json)
        die(1, "calendar_error", blob or "osascript failed", as_json)
    raw = (proc.stdout or "").strip()
    if not raw:
        die(1, "calendar_error", "Calendar returned an empty response", as_json)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        die(1, "calendar_error", "Calendar returned non-JSON: " + raw[:400], as_json)
    if data.get("error") in ("automation_denied", "calendar_tcc"):
        die(3, data["error"], data.get("message") or "", as_json)
    return data


def emit(data, as_json, text_fn):
    if not data.get("ok", False):
        soft = {
            "needs_force", "unsupported", "missing_target", "missing_title",
            "missing_calendar", "missing_change", "missing_query", "ambiguous",
            "bad_request", "not_found", "query_too_broad", "read_only_calendar",
        }
        code = 2 if data.get("error") in soft else 1
        if data.get("error") in ("automation_denied", "calendar_tcc"):
            code = 3
        if data.get("error") == "automation_timeout":
            code = 4
        if as_json:
            data.setdefault("tool", "grok-calendar")
            data.setdefault("version", VERSION)
            print(json.dumps(data))
        else:
            print(f"grok-calendar: {data.get('error')}: {data.get('message', '')}", file=sys.stderr)
            for row in data.get("matches") or []:
                label = row.get("title") or row.get("name") or "(untitled)"
                ident = row.get("uid") or row.get("id") or ""
                extra = row.get("start") or ""
                print(f"  {extra}  {label}  {ident}".strip(), file=sys.stderr)
            if data.get("error") in ("automation_denied", "calendar_tcc"):
                print(AUTH_HINT, file=sys.stderr)
        raise SystemExit(code)
    if as_json:
        data.setdefault("tool", "grok-calendar")
        data.setdefault("version", VERSION)
        print(json.dumps(data))
    else:
        text_fn(data)


def clock(value):
    if not value:
        return "?"
    # 2026-10-03T09:00:00-05:00 → 2026-10-03 09:00
    text = str(value)
    if len(text) >= 16 and text[10] == "T":
        return text[:10] + " " + text[11:16]
    return text


def print_doctor(data):
    app = data.get("calendarApp") or {}
    print(f"grok-calendar {VERSION}  ok")
    print("backend: Calendar.app JXA")
    print(f"automation: {data.get('automation')}")
    print("writes: off unless you run create, update, or delete --force")
    print(f"Calendar {app.get('version')} ({app.get('id')})")
    print(f"calendars: {data.get('calendars')}   writable: {data.get('writableCalendars')}")


def print_calendars(data):
    print(f"{data.get('count')} calendars")
    for row in data.get("calendars") or []:
        flag = "writable" if row.get("writable") else "read-only"
        print(f"  {row.get('name')}  {flag}  {row.get('id')}")


def print_events(data):
    window = f"{data.get('from')} → {data.get('to')}"
    if data.get("query"):
        print(f"{data.get('count')} match(es) for {data.get('query')!r}  {window}")
    else:
        print(f"{data.get('count')} event(s)  {window}")
    for row in data.get("events") or []:
        if row.get("allDay"):
            when = str(row.get("start") or "")[:10] + " all-day"
        else:
            when = clock(row.get("start")) + "–" + clock(row.get("end"))[11:16]
        print(f"  {when}  {row.get('title')}  · {row.get('calendar')}")
    if data.get("truncated"):
        print("(showing the first matches; pass --limit or a narrower range)")


def print_show(data):
    ev = data.get("event") or {}
    print(ev.get("title") or "(no title)")
    print(f"uid: {ev.get('uid')}")
    if ev.get("allDay"):
        print(f"when: {str(ev.get('start') or '')[:10]} all-day → {str(ev.get('end') or '')[:10]}")
    else:
        print(f"when: {clock(ev.get('start'))} – {clock(ev.get('end'))}")
    print(f"calendar: {ev.get('calendar')}  ({'writable' if ev.get('writable') else 'read-only'})")
    if ev.get("location"):
        print(f"location: {ev.get('location')}")
    if ev.get("status"):
        print(f"status: {ev.get('status')}")
    if ev.get("url"):
        print(f"url: {ev.get('url')}")
    if ev.get("recurrence"):
        print(f"recurrence: {ev.get('recurrence')}")
    if ev.get("notes"):
        print("notes: " + str(ev.get("notes"))[:400])


def print_write(data):
    if data.get("deleted"):
        print(f"deleted {data.get('title')}  {data.get('uid')}  · {data.get('calendar')}")
        return
    verb = "created" if data.get("created") else "updated"
    print(f"{verb} {data.get('title')}  {clock(data.get('start'))}  {data.get('uid')}  · {data.get('calendar')}")


def add_json(sp):
    sp.add_argument("--json", action="store_true")


def add_range(sp, default_days):
    sp.add_argument("--from", dest="from_date", help="YYYY-MM-DD or YYYY-MM-DD HH:MM")
    sp.add_argument("--to", dest="to_date", help="YYYY-MM-DD (inclusive) or YYYY-MM-DD HH:MM")
    sp.add_argument("--days", type=int, default=None, help=f"window length when --to is omitted (default {default_days})")
    sp.add_argument("--today", action="store_true")
    sp.add_argument("--calendar", help="exact calendar name")
    sp.add_argument("--limit", type=int, default=25)


def resolve_range(args, default_days, search=False):
    today = date.today()
    today_flag = getattr(args, "today", False)
    from_date = getattr(args, "from_date", None)
    to_date = getattr(args, "to_date", None)
    days_arg = getattr(args, "days", None)
    if today_flag:
        start = today
        end = today
    else:
        if from_date:
            start = parse_day(from_date)
        elif search and days_arg is None:
            start = today - timedelta(days=30)
        else:
            start = today
        if to_date:
            end = parse_day(to_date)
        elif search and days_arg is None and not from_date:
            end = today + timedelta(days=180)
        else:
            days = days_arg if days_arg is not None else default_days
            if days < 1 or days > 366:
                die(2, "bad_request", "--days must be 1..366.", False)
            end = start + timedelta(days=days - 1)
    return start.isoformat(), end.isoformat()


def parse_day(value):
    text = value.strip()
    try:
        if len(text) >= 10:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
    except ValueError:
        pass
    die(2, "bad_request", f"Could not read date {value!r}. Use YYYY-MM-DD.", False)


def build_parser():
    p = argparse.ArgumentParser(prog="grok-calendar", description="Calendar.app CLI (JXA). Read by default.")
    p.add_argument("--version", action="version", version=f"grok-calendar {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("doctor", help="Check Automation access and calendar counts")
    add_json(sp)

    sp = sub.add_parser("calendars", help="List calendars (no events)")
    add_json(sp)

    sp = sub.add_parser("list", help="Events overlapping a date range (titles and times)")
    add_range(sp, 7)
    add_json(sp)

    sp = sub.add_parser("search", help="Find events by title or location inside a window")
    sp.add_argument("query")
    add_range(sp, 180)
    add_json(sp)

    sp = sub.add_parser("show", help="One event by --uid, or one exact title match")
    sp.add_argument("query", nargs="?")
    sp.add_argument("--uid")
    sp.add_argument("--from", dest="from_date")
    sp.add_argument("--to", dest="to_date")
    sp.add_argument("--calendar")
    add_json(sp)

    sp = sub.add_parser("create", help="Create one event (mutation)")
    sp.add_argument("--calendar", required=True)
    sp.add_argument("--title", required=True)
    sp.add_argument("--start", required=True, help="YYYY-MM-DD or YYYY-MM-DD HH:MM")
    sp.add_argument("--end", help="defaults to one hour, or next day if --all-day")
    sp.add_argument("--all-day", action="store_true")
    sp.add_argument("--location")
    sp.add_argument("--notes")
    sp.add_argument("--dry-run", action="store_true", help="Validate args only; do not call Calendar.app")
    add_json(sp)

    sp = sub.add_parser("update", help="Change one event by uid (mutation, same calendar)")
    sp.add_argument("--uid", required=True)
    sp.add_argument("--title")
    sp.add_argument("--start")
    sp.add_argument("--end")
    sp.add_argument("--all-day", action="store_true")
    sp.add_argument("--timed", action="store_true", help="clear all-day")
    sp.add_argument("--location")
    sp.add_argument("--notes")
    add_json(sp)

    sp = sub.add_parser("delete", help="Delete one event by uid")
    sp.add_argument("--uid", required=True)
    sp.add_argument("--force", action="store_true")
    add_json(sp)

    sp = sub.add_parser("gaps", help="What Calendar.app can do that this CLI cannot")
    add_json(sp)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    as_json = getattr(args, "json", False)
    if args.cmd == "gaps":
        data = {"ok": True, "tool": "grok-calendar", "version": VERSION, "gaps": GAPS}
        emit(data, as_json, lambda d: print("\n".join("- " + g for g in d["gaps"])))
        return

    if args.cmd == "doctor":
        data = call_jxa({"op": "doctor"}, DOCTOR_TIMEOUT, as_json)
        data["version"] = VERSION
        emit(data, as_json, print_doctor)
        return
    if args.cmd == "calendars":
        data = call_jxa({"op": "calendars"}, DEFAULT_TIMEOUT, as_json)
        emit(data, as_json, print_calendars)
        return
    if args.cmd == "list":
        start, end = resolve_range(args, 7, search=False)
        data = call_jxa({
            "op": "list",
            "from": start,
            "to": end,
            "calendar": args.calendar,
            "limit": args.limit,
        }, LONG_TIMEOUT, as_json)
        emit(data, as_json, print_events)
        return
    if args.cmd == "search":
        start, end = resolve_range(args, 180, search=True)
        data = call_jxa({
            "op": "search",
            "query": args.query,
            "from": start,
            "to": end,
            "calendar": args.calendar,
            "limit": args.limit,
        }, LONG_TIMEOUT, as_json)
        emit(data, as_json, print_events)
        return
    if args.cmd == "show":
        payload = {"op": "show", "uid": args.uid, "query": args.query, "calendar": args.calendar}
        if args.from_date or args.to_date:
            start, end = resolve_range(args, 180, search=True)
            payload["from"] = start
            payload["to"] = end
        elif args.query and not args.uid:
            start, end = resolve_range(args, 180, search=True)
            payload["from"] = start
            payload["to"] = end
        data = call_jxa(payload, LONG_TIMEOUT, as_json)
        emit(data, as_json, print_show)
        return
    if args.cmd == "create":
        if not (args.title or "").strip():
            die(2, "missing_title", "create needs --title.", as_json)
        if not (args.calendar or "").strip():
            die(2, "missing_calendar", "create needs --calendar.", as_json)
        if not (args.start or "").strip():
            die(2, "bad_request", "create needs --start as YYYY-MM-DD or YYYY-MM-DD HH:MM.", as_json)
        if args.dry_run:
            data = {
                "ok": True,
                "dryRun": True,
                "wouldCreate": True,
                "calendar": args.calendar,
                "title": args.title,
                "start": args.start,
                "end": args.end,
                "allDay": bool(args.all_day),
                "location": args.location,
                "notes": args.notes,
                "message": "dry-run: Calendar.app was not called.",
            }
            emit(data, as_json, lambda d: print(f"dry-run create {d.get('title')!r} on {d.get('calendar')} at {d.get('start')} (Calendar not called)"))
            return
        data = call_jxa({
            "op": "create",
            "calendar": args.calendar,
            "title": args.title,
            "start": args.start,
            "end": args.end,
            "allDay": bool(args.all_day),
            "location": args.location,
            "notes": args.notes,
        }, LONG_TIMEOUT, as_json)
        emit(data, as_json, print_write)
        return
    if args.cmd == "update":
        if args.all_day and args.timed:
            die(2, "bad_request", "Pass only one of --all-day and --timed.", as_json)
        all_day = True if args.all_day else False if args.timed else None
        data = call_jxa({
            "op": "update",
            "uid": args.uid,
            "title": args.title,
            "start": args.start,
            "end": args.end,
            "allDay": all_day,
            "location": args.location,
            "notes": args.notes,
        }, LONG_TIMEOUT, as_json)
        emit(data, as_json, print_write)
        return
    if args.cmd == "delete":
        if not args.force:
            die(2, "needs_force", "delete refuses without --force. This removes one event by --uid. There is no mass delete and no delete-all.", as_json)
        data = call_jxa({"op": "delete", "uid": args.uid, "force": True}, LONG_TIMEOUT, as_json)
        emit(data, as_json, print_write)
        return
    die(2, "bad_request", "Unknown command", as_json)


if __name__ == "__main__":
    main()
