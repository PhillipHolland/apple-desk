#!/usr/bin/env python3
"""grok-calendar command line. Calendar.app via JXA. Not a cloud calendar API."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

VERSION = "0.1.6"
LIB = Path(__file__).resolve().parent / "calendar.js"
sys.path.insert(0, str(Path(__file__).resolve().parent))
import cache as calcache  # noqa: E402


def wake_calendar():
    """Nudge Calendar.app awake without stealing focus. Safe when already running."""
    try:
        subprocess.run(["open", "-ga", "Calendar"], capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        pass


GAPS = [
    "Direct EventKit is not used. A command-line binary has no NSCalendarsUsageDescription, so macOS often will not show the Calendars privacy prompt for the binary. This CLI asks Calendar.app over Apple Events. The usual grant is Automation (Grok Bot or Grok Bot Helper → Calendar). If Calendar still refuses the data, also enable Grok Bot and Grok Bot Helper under Privacy & Security → Calendars, then quit and reopen Grok Bot.",
    "Reads are the default. create and update write when you run them. delete and alarm refuse without --force. There is no delete-all and no command that removes every alarm.",
    "show returns attendeeCount and alarmCount only. It does not list attendee or RSVP names, participation status, or email addresses. Those names stay omitted unless you explicitly ask, and this CLI has no command that prints them. It does not send invites or propose a new time. It does not set travel time or change availability.",
    "alarm --uid --minutes N adds one display alarm N minutes before the start (Calendar's trigger interval, stored negative). Without --force it is a dry-run and does not call Calendar.app. Sound, mail, and open-file alarms are not created.",
    "Recurrence on show is a small object (summary, and frequency or until when Calendar exposes them). This CLI does not create or edit a series, and it does not target one occurrence versus the whole series.",
    "Events cannot be moved between calendars. Calendar's scripting definition has no calendar property on an event, and the event does not respond to move. This CLI does not copy an event and delete the original, and it does not use EventKit. update changes fields on the event's current calendar only.",
    "Subscribed and read-only calendars (holidays, birthdays, some shared calendars) can be listed but not written.",
    "list and search use the local index (~/.cache/grok-calendar) when present. Pass --live to read Calendar.app. Pass --calendar-id when two calendars share a name. A calendar with more than 800 overlapping events in the window is refused.",
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

# Doctor stays lean (names only). Heavy list/search can take longer per calendar.
DOCTOR_TIMEOUT = 25
DEFAULT_TIMEOUT = 12
NAME_TIMEOUT = 12
LONG_TIMEOUT = 36


def parse_stamp(value):
    """Offline check. YYYY-MM-DD or YYYY-MM-DD HH:MM. Does not call Calendar."""
    raw = (value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return False


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


def call_jxa_result(payload, timeout):
    """Like call_jxa, but returns an error object instead of exiting."""
    proc = subprocess.run(
        ["perl", "-e", "alarm shift @ARGV; exec @ARGV", str(timeout), "osascript", "-l", "JavaScript", str(LIB), "--", json.dumps(payload)],
        capture_output=True,
        text=True,
    )
    blob = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
    if proc.returncode in (-14, 142) or "Alarm clock" in blob:
        return {"ok": False, "error": "automation_timeout", "code": 4, "message": f"Timed out after {timeout}s"}
    if proc.returncode != 0:
        if "-1743" in blob or "Not authorized" in blob:
            return {"ok": False, "error": "automation_denied", "code": 3, "message": blob[:240]}
        if "-1712" in blob or "timed out" in blob.lower():
            return {"ok": False, "error": "automation_timeout", "code": 4, "message": blob[:240]}
        return {"ok": False, "error": "calendar_error", "code": 1, "message": (blob or "osascript failed")[:240]}
    raw = (proc.stdout or "").strip()
    if not raw:
        return {"ok": False, "error": "calendar_error", "code": 1, "message": "empty response"}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"ok": False, "error": "calendar_error", "code": 1, "message": "non-JSON"}
    return data


def calendar_count():
    data = call_jxa_result({"op": "doctor"}, DOCTOR_TIMEOUT)
    if not data.get("ok"):
        return data
    try:
        return {"ok": True, "calendars": int(data.get("calendars") or 0), "doctor": data}
    except (TypeError, ValueError):
        return {"ok": False, "error": "calendar_error", "message": "doctor did not return a count"}


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
    print("writes: create and update are live; delete and alarm need --force")
    print(f"Calendar {app.get('version')} ({app.get('id')})")
    print(f"calendars: {data.get('calendars')}   writable: {data.get('writableCalendars') if data.get('writableCalendars') is not None else '(see calendars)'}")


def print_calendars(data):
    print(f"{data.get('count')} calendars")
    for row in data.get("calendars") or []:
        flag = "writable" if row.get("writable") else "read-only"
        print(f"  {row.get('name')}  {flag}  {row.get('id')}")


def print_events(data):
    window = f"{data.get('from')} → {data.get('to')}"
    src = f"  [{data.get('source')}]" if data.get("source") else ""
    if data.get("query"):
        print(f"{data.get('count')} match(es) for {data.get('query')!r}  {window}{src}")
    else:
        print(f"{data.get('count')} event(s)  {window}{src}")
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


def print_alarm(data):
    when = f"{data.get('minutesBefore')} minutes before"
    if data.get("dryRun"):
        print(f"dry-run alarm {data.get('uid')} {when} (Calendar not called)")
        return
    calendar = data.get("calendar") or ""
    suffix = f"  · {calendar}" if calendar else ""
    print(f"alarm {data.get('uid')} {when}{suffix}")


def add_json(sp):
    sp.add_argument("--json", action="store_true")


def add_range(sp, default_days):
    sp.add_argument("--from", dest="from_date", help="YYYY-MM-DD or YYYY-MM-DD HH:MM")
    sp.add_argument("--to", dest="to_date", help="YYYY-MM-DD (inclusive) or YYYY-MM-DD HH:MM")
    sp.add_argument("--days", type=int, default=None, help=f"window length when --to is omitted (default {default_days})")
    sp.add_argument("--today", action="store_true")
    sp.add_argument("--calendar", help="exact calendar name; resolved to indexes, one Apple Event each")
    sp.add_argument("--calendar-id", dest="calendar_id", help="ignored for live list; indexes are the portable key")
    sp.add_argument("--index", type=int, default=None, help="one calendar index from doctor/name-at")
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

    sp = sub.add_parser("calendars", help="List calendar names, one index per Apple Event")
    sp.add_argument("--ids", action="store_true", help="accepted; ids are indexes")
    sp.add_argument("--full", action="store_true", help="accepted; still names and indexes only")
    add_json(sp)

    sp = sub.add_parser("name-at", help="Name of one calendar index")
    sp.add_argument("--index", type=int, required=True)
    add_json(sp)

    sp = sub.add_parser("list", help="Events overlapping a date range (index by default)")
    add_range(sp, 7)
    sp.add_argument("--live", action="store_true", help="query Calendar.app instead of the local index")
    sp.add_argument("--light", action="store_true", help="titles and times only; do not read locations")
    sp.add_argument("--all", action="store_true", help="accepted for compatibility; live list already includes every calendar")
    add_json(sp)

    sp = sub.add_parser("search", help="Find events by title (index by default)")
    sp.add_argument("query")
    add_range(sp, 180)
    sp.add_argument("--live", action="store_true", help="query Calendar.app instead of the local index")
    sp.add_argument("--all", action="store_true", help="accepted for compatibility; live list already includes every calendar")
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
    sp.add_argument("--dry-run", action="store_true", help="Validate only; do not call Calendar.app")
    add_json(sp)

    sp = sub.add_parser("delete", help="Delete one event by uid")
    sp.add_argument("--uid", required=True)
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--dry-run", action="store_true", help="Do not call Calendar.app")
    add_json(sp)

    sp = sub.add_parser("alarm", help="Add one display alarm. Dry-run unless --force. Does not list attendees.")
    sp.add_argument("--uid", required=True)
    sp.add_argument("--minutes", type=int, required=True, help="minutes before the start (0..40320)")
    sp.add_argument("--force", action="store_true", help="Apply in Calendar.app. Without this, Calendar is not called.")
    sp.add_argument("--dry-run", action="store_true", help="Do not call Calendar.app")
    add_json(sp)

    sp = sub.add_parser("gaps", help="What Calendar.app can do that this CLI cannot")
    add_json(sp)
    return p


def live_indexes(index, name, as_json):
    if index is not None:
        return [index]
    if not name:
        die(2, "needs_calendar", "Pass --index or --calendar. A live list does not walk every calendar in one Apple Event.", as_json)
    counted = calendar_count()
    if not counted.get("ok"):
        die(4 if counted.get("code") == 4 else 1, counted.get("error") or "calendar_error", counted.get("message") or "", as_json)
    found = []
    for i in range(counted["calendars"]):
        row = call_jxa_result({"op": "calendarAt", "index": i}, NAME_TIMEOUT)
        if row.get("ok") and (row.get("name") or "") == name:
            found.append(i)
    if not found:
        die(2, "not_found", f"No calendar named {name!r}.", as_json)
    return found


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
    if args.cmd == "name-at":
        data = call_jxa({"op": "calendarAt", "index": args.index}, NAME_TIMEOUT, as_json)
        emit(data, as_json, lambda d: print(f"{d.get('index')}  {d.get('name')}"))
        return
    if args.cmd == "calendars":
        counted = calendar_count()
        if not counted.get("ok"):
            die(4 if counted.get("code") == 4 else 1, counted.get("error") or "calendar_error", counted.get("message") or "", as_json)
        rows = []
        skipped = []
        for i in range(counted["calendars"]):
            row = call_jxa_result({"op": "calendarAt", "index": i}, NAME_TIMEOUT)
            if row.get("ok"):
                rows.append({"index": i, "id": i, "name": row.get("name") or "(unnamed)", "writable": None})
            else:
                skipped.append(i)
        data = {"ok": True, "count": len(rows), "calendars": rows, "skippedIndexes": skipped, "tool": "grok-calendar", "version": VERSION}
        emit(data, as_json, print_calendars)
        return
    if args.cmd == "list":
        start, end = resolve_range(args, 7, search=False)
        if not args.live:
            data = calcache.list_events(start, end, args.calendar, None, args.limit)
            if data.get("ok"):
                emit(data, as_json, print_events)
                return
            # fall through to live when index missing
        indexes = live_indexes(getattr(args, "index", None), getattr(args, "calendar", None), as_json)
        events = []
        skipped = []
        truncated = False
        for index in indexes:
            piece = call_jxa_result({
                "op": "list",
                "from": start,
                "to": end,
                "calendarIndex": index,
                "limit": args.limit,
                "light": True,
            }, LONG_TIMEOUT)
            if not piece.get("ok"):
                if piece.get("error") in ("automation_denied", "calendar_tcc"):
                    die(3, piece["error"], piece.get("message") or "", as_json)
                if len(indexes) == 1:
                    code = 4 if piece.get("error") in ("timeout", "automation_timeout") else 1
                    die(code, piece.get("error") or "calendar_error", piece.get("message") or "calendar list failed", as_json)
                skipped.append({"index": index, "error": piece.get("error")})
                continue
            events.extend(piece.get("events") or [])
            truncated = truncated or bool(piece.get("truncated"))
        events.sort(key=lambda row: str(row.get("start") or ""))
        data = {
            "ok": True,
            "from": start,
            "to": end,
            "count": len(events),
            "truncated": truncated,
            "skipped": skipped,
            "events": events[: args.limit] if args.limit else events,
            "source": "live",
            "tool": "grok-calendar",
            "version": VERSION,
        }
        emit(data, as_json, print_events)
        return
    if args.cmd == "search":
        start, end = resolve_range(args, 180, search=True)
        if not args.live:
            data = calcache.list_events(start, end, args.calendar, args.query, args.limit)
            if data.get("ok"):
                emit(data, as_json, print_events)
                return
        data = call_jxa({
            "op": "search",
            "query": args.query,
            "from": start,
            "to": end,
            "calendar": args.calendar,
            "limit": args.limit,
            "writableOnly": not args.all,
        }, LONG_TIMEOUT, as_json)
        data["source"] = "live"
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
        start_dt = parse_stamp(args.start)
        if start_dt is False:
            die(2, "bad_request", "start must be YYYY-MM-DD or YYYY-MM-DD HH:MM. Calendar was not called.", as_json)
        if args.end:
            end_dt = parse_stamp(args.end)
            if end_dt is False:
                die(2, "bad_request", "end must be YYYY-MM-DD or YYYY-MM-DD HH:MM. Calendar was not called.", as_json)
            if start_dt and end_dt and end_dt < start_dt:
                die(2, "bad_request", "end is before start. Calendar was not called.", as_json)
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
        if args.start and parse_stamp(args.start) is False:
            die(2, "bad_request", "start must be YYYY-MM-DD or YYYY-MM-DD HH:MM. Calendar was not called.", as_json)
        if args.end and parse_stamp(args.end) is False:
            die(2, "bad_request", "end must be YYYY-MM-DD or YYYY-MM-DD HH:MM. Calendar was not called.", as_json)
        all_day = True if args.all_day else False if args.timed else None
        if args.dry_run:
            data = {
                "ok": True,
                "dryRun": True,
                "wouldUpdate": True,
                "uid": args.uid,
                "title": args.title,
                "start": args.start,
                "end": args.end,
                "message": "dry-run: Calendar.app was not called.",
            }
            emit(data, as_json, lambda d: print(f"dry-run update {d.get('uid')} (Calendar not called)"))
            return
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
        if args.dry_run:
            data = {
                "ok": True,
                "dryRun": True,
                "wouldDelete": True,
                "uid": args.uid,
                "message": "dry-run: Calendar.app was not called. A real delete still needs --force.",
            }
            emit(data, as_json, lambda d: print(f"dry-run delete {d.get('uid')} (Calendar not called)"))
            return
        if not args.force:
            die(2, "needs_force", "delete refuses without --force. This removes one event by --uid. There is no mass delete and no delete-all.", as_json)
        data = call_jxa({"op": "delete", "uid": args.uid, "force": True}, LONG_TIMEOUT, as_json)
        emit(data, as_json, print_write)
        return
    if args.cmd == "alarm":
        uid = (args.uid or "").strip()
        if not uid:
            die(2, "missing_target", "alarm needs --uid. Calendar was not called.", as_json)
        minutes = args.minutes
        if isinstance(minutes, bool) or not isinstance(minutes, int) or minutes < 0 or minutes > 40320:
            die(2, "bad_request", "alarm --minutes must be an integer from 0 through 40320 (minutes before the start). Calendar was not called.", as_json)
        if args.dry_run or not args.force:
            data = {
                "ok": True,
                "dryRun": True,
                "applied": False,
                "op": "alarm",
                "uid": uid,
                "minutesBefore": minutes,
                "message": "dry-run: Calendar.app was not called. Pass --force to apply.",
            }
            emit(data, as_json, print_alarm)
            return
        data = call_jxa({
            "op": "alarm",
            "uid": uid,
            "minutesBefore": minutes,
            "force": True,
        }, LONG_TIMEOUT, as_json)
        emit(data, as_json, print_alarm)
        return
    die(2, "bad_request", "Unknown command", as_json)


if __name__ == "__main__":
    main()
