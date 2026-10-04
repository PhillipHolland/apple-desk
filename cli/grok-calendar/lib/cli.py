#!/usr/bin/env python3
"""Apple Desk's Calendar CLI: one owned EventKit backend, no cache/PIM fallback."""
from __future__ import annotations
import argparse
import base64
from datetime import date, datetime, timedelta, timezone
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "shared"))
from agent_core import ToolError, StateStore, emit_success, emit_error  # noqa: E402

VERSION = "0.2.0"
HELPER = Path(__file__).resolve().parents[3] / "native/dist/apple-desk-calendar"
FIELDS = {"calendarId", "title", "start", "end", "allDay", "timeZone", "location", "notes", "url", "availability", "alarms", "recurrence"}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise ToolError("INVALID_ARGUMENT", message)


def local_zone():
    """Read public system timezone rules, including future DST transitions."""
    try:
        with open("/etc/localtime", "rb") as stream:
            return ZoneInfo.from_file(stream)
    except OSError as exc:
        raise ToolError("INVALID_TIME_ZONE", "Cannot read system time zone; supply --time-zone.") from exc


def zone(name=None):
    if name is None:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ToolError("INVALID_TIME_ZONE", f"Unknown IANA time zone: {name!r}.") from exc


def stamp(value, tz=None, all_day=False):
    """Reject normalized dates, nonexistent local times, and ambiguous wall times."""
    if not isinstance(value, str):
        raise ToolError("INVALID_INPUT", "Dates must be strings.")
    text = value.strip().replace(" ", "T", 1)
    if all_day:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", text):
            raise ToolError("INVALID_INPUT", "All-day dates must be YYYY-MM-DD; end is exclusive.")
        try:
            return datetime.combine(date.fromisoformat(text), datetime.min.time(), tz or local_zone())
        except ValueError as exc:
            raise ToolError("INVALID_INPUT", "Invalid all-day date.") from exc
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?)?", text):
        raise ToolError("INVALID_INPUT", "Use ISO 8601 or YYYY-MM-DD HH:MM with --time-zone.")
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ToolError("INVALID_INPUT", f"Invalid date: {value!r}.") from exc
    if result.tzinfo is not None:
        return result
    if tz is None:
        raise ToolError("INVALID_INPUT", "Local timed dates require --time-zone or timeZone; otherwise supply an explicit UTC offset.")
    candidates = []
    for fold in (0, 1):
        candidate = result.replace(tzinfo=tz, fold=fold)
        if candidate.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None) == result:
            if not any(c.timestamp() == candidate.timestamp() for c in candidates):
                candidates.append(candidate)
    if not candidates:
        raise ToolError("INVALID_INPUT", "This local time does not exist due to a daylight-saving transition.")
    if len(candidates) > 1:
        raise ToolError("AMBIGUOUS_TIME", "This local time occurs twice; supply an explicit UTC offset.")
    return candidates[0]


def iso(value):
    return value.isoformat(timespec="microseconds").replace("+00:00", "Z")


def integer(value, name, minimum=0, maximum=100000):
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise ToolError("INVALID_INPUT", f"{name} must be an integer from {minimum} through {maximum}.")
    return value


def json_object(path):
    try:
        raw = sys.stdin.read(1_048_577) if path == "-" else Path(path).expanduser().read_text(encoding="utf-8")
        if len(raw.encode()) > 1_048_576:
            raise ToolError("INVALID_INPUT", "Input JSON exceeds 1 MiB.")
        value = json.loads(raw)
    except (OSError, ValueError) as exc:
        raise ToolError("INVALID_INPUT", "Cannot read valid input JSON.") from exc
    if not isinstance(value, dict):
        raise ToolError("INVALID_INPUT", "Input must be a JSON object.")
    return value


def parse_embedded_json(text, name):
    try:
        return json.loads(text)
    except ValueError as exc:
        raise ToolError("INVALID_INPUT", f"{name} must contain JSON.") from exc


def validate_reference(target, options):
    if not isinstance(target, str) or not target.strip():
        raise ToolError("INVALID_INPUT", "Supply --uid EVENT or an event reference.")
    if target.startswith("event:"):
        try:
            raw = target[6:]
            ref = json.loads(base64.b64decode(raw + "=" * (-len(raw) % 4), altchars=b"-_", validate=True))
            if not isinstance(ref, dict) or not isinstance(ref.get("id"), str) or not ref["id"]:
                raise ValueError("missing ID")
        except (ValueError, TypeError) as exc:
            raise ToolError("INVALID_INPUT", "Malformed event reference.") from exc
        if options.get("calendarId") and ref.get("calendarId") and options["calendarId"] != ref["calendarId"]:
            raise ToolError("STALE_REFERENCE", "Calendar ID conflicts with the event reference.")
        if ref.get("occurrence"):
            saved = stamp(ref["occurrence"])
            if options.get("occurrence") and abs(stamp(options["occurrence"]).timestamp() - saved.timestamp()) >= .5:
                raise ToolError("STALE_REFERENCE", "Occurrence conflicts with the event reference.")
            if not options.get("scope"):
                raise ToolError("INVALID_INPUT", "A recurring mutation requires --scope this|future.")
    if options.get("scope") not in (None, "this", "future"):
        raise ToolError("INVALID_INPUT", "scope must be this or future.")


def event_input(args, creating):
    value = json_object(args.input) if args.input else {}
    for attr, key in (("title", "title"), ("start", "start"), ("end", "end"), ("location", "location"), ("notes", "notes"), ("url", "url"), ("availability", "availability"), ("time_zone", "timeZone")):
        if getattr(args, attr, None) is not None:
            value[key] = getattr(args, attr)
    if args.all_day:
        value["allDay"] = True
    if args.timed:
        value["allDay"] = False
    if args.alarms is not None:
        value["alarms"] = parse_embedded_json(args.alarms, "alarms")
    if args.recurrence is not None:
        value["recurrence"] = parse_embedded_json(args.recurrence, "recurrence")
    if creating and args.calendar_id:
        value["calendarId"] = args.calendar_id
    unknown = set(value) - FIELDS
    if unknown:
        raise ToolError("INVALID_INPUT", "Unsupported event fields: " + ", ".join(sorted(unknown)))
    for key in ("calendarId", "title", "timeZone"):
        if key in value and (not isinstance(value[key], str) or not value[key].strip()):
            raise ToolError("INVALID_INPUT", f"{key} must be a nonempty string.")
    if "allDay" in value and not isinstance(value["allDay"], bool):
        raise ToolError("INVALID_INPUT", "allDay must be boolean.")
    for key in ("notes", "location", "url"):
        if key in value and value[key] is not None and not isinstance(value[key], str):
            raise ToolError("INVALID_INPUT", f"{key} must be a string or null.")
    if value.get("url") is not None and not re.match(r"^[A-Za-z][A-Za-z0-9+.-]*:", value["url"]):
        raise ToolError("INVALID_INPUT", "url must be an absolute URL.")
    if "availability" in value and value["availability"] not in {"busy", "free", "tentative", "unavailable"}:
        raise ToolError("INVALID_INPUT", "Invalid availability.")
    tz = zone(value.get("timeZone"))
    all_day = value.get("allDay", False)
    if all_day:
        # EventKit all-day dates are floating system-calendar dates, not instants in a requested zone.
        tz = local_zone()
        value.pop("timeZone", None)
    if creating:
        if not value.get("title") or not value.get("start"):
            raise ToolError("INVALID_INPUT", "Creation requires title and start.")
        if not value.get("calendarId") and not args.calendar:
            raise ToolError("INVALID_INPUT", "Creation requires --calendar-id, calendarId, or a unique --calendar name.")
        value.setdefault("allDay", False)
    elif not value:
        raise ToolError("INVALID_INPUT", "Provide at least one event change.")
    if not creating and "allDay" in value and not all(key in value for key in ("start", "end")):
        raise ToolError("INVALID_INPUT", "Changing allDay requires both start and end.")
    parsed = {}
    for key in ("start", "end"):
        if key in value:
            parsed[key] = stamp(value[key], tz, all_day)
            value[key] = parsed[key].date().isoformat() if all_day else iso(parsed[key])
    if creating and "end" not in value:
        start = parsed["start"]
        if all_day:
            value["end"] = (start.date() + timedelta(days=1)).isoformat()
            parsed["end"] = stamp(value["end"], tz, True)
        else:
            parsed["end"] = datetime.fromtimestamp(start.timestamp() + 3600, timezone.utc)
            value["end"] = iso(parsed["end"])
    if "start" in parsed and "end" in parsed and parsed["end"].timestamp() <= parsed["start"].timestamp():
        raise ToolError("INVALID_INPUT", "end must follow start; all-day end is exclusive.")
    if "alarms" in value:
        alarms = value["alarms"]
        if not isinstance(alarms, list) or len(alarms) > 20:
            raise ToolError("INVALID_INPUT", "alarms must be an array of at most 20 objects.")
        for alarm in alarms:
            if not isinstance(alarm, dict) or len(alarm) != 1:
                raise ToolError("INVALID_INPUT", "Each alarm requires exactly minutesBefore or at.")
            if "minutesBefore" in alarm:
                integer(alarm["minutesBefore"], "minutesBefore", maximum=525600)
            elif "at" in alarm:
                alarm["at"] = iso(stamp(alarm["at"], tz))
            else:
                raise ToolError("INVALID_INPUT", "Unsupported alarm field.")
    if value.get("recurrence") is not None:
        recurrence = value["recurrence"]
        if not isinstance(recurrence, dict) or set(recurrence) - {"frequency", "interval", "count", "until", "weekdays"} or recurrence.get("frequency") not in {"daily", "weekly", "monthly", "yearly"}:
            raise ToolError("INVALID_INPUT", "Invalid recurrence frequency or fields.")
        integer(recurrence.get("interval", 1), "interval", minimum=1, maximum=1000)
        if "count" in recurrence and "until" in recurrence:
            raise ToolError("INVALID_INPUT", "Use recurrence count or until, not both.")
        if "count" in recurrence:
            integer(recurrence["count"], "count", minimum=1)
        if "until" in recurrence:
            until = stamp(recurrence["until"], tz or (local_zone() if all_day else None))
            if parsed.get("start") and until.timestamp() < parsed["start"].timestamp():
                raise ToolError("INVALID_INPUT", "Recurrence end precedes event start.")
            recurrence["until"] = iso(until)
        if "weekdays" in recurrence:
            days = recurrence["weekdays"]
            if recurrence["frequency"] == "daily" or not isinstance(days, list) or not 1 <= len(days) <= 7:
                raise ToolError("INVALID_INPUT", "weekdays requires 1...7 Sunday-based weekday numbers, except daily recurrence.")
            for day in days:
                integer(day, "weekday", minimum=1, maximum=7)
            if len(days) != len(set(days)):
                raise ToolError("INVALID_INPUT", "Duplicate recurrence weekdays.")
    return value


def native(action, options=None, value=None, target=None):
    if not HELPER.is_file() or not os.access(HELPER, os.X_OK):
        raise ToolError("BACKEND_UNAVAILABLE", "Owned EventKit helper is missing. Run native/build.sh and reinstall Apple Desk.", {"path": str(HELPER)})
    request = {"action": action, "options": options or {}}
    if value is not None:
        request["input"] = value
    if target is not None:
        request["target"] = target
    mutating = action in {"create", "update", "delete"}
    try:
        proc = subprocess.run([str(HELPER)], input=json.dumps(request, allow_nan=False), text=True, capture_output=True, timeout=100 if action == "permissions" else 45)
    except subprocess.TimeoutExpired as exc:
        raise ToolError("WRITE_STATUS_UNKNOWN" if mutating else "TIMEOUT", "Native calendar write timed out; inspect current state before retrying." if mutating else "Native calendar read timed out; no calendar write was attempted.", {"readOnly": not mutating, "writeMayHaveTakenEffect": mutating}) from exc
    except OSError as exc:
        raise ToolError("BACKEND_UNAVAILABLE", str(exc)) from exc
    try:
        response = json.loads(proc.stdout)
        if not isinstance(response, dict) or not isinstance(response.get("ok"), bool):
            raise ValueError("invalid response envelope")
    except ValueError as exc:
        raise ToolError("WRITE_STATUS_UNKNOWN" if mutating else "BACKEND_ERROR", "Native calendar helper returned an invalid response.", {"exitCode": proc.returncode, "readOnly": not mutating, "writeMayHaveTakenEffect": mutating}) from exc
    if not response["ok"]:
        error = response.get("error") or {}
        if not isinstance(error, dict):
            raise ToolError("WRITE_STATUS_UNKNOWN" if mutating else "BACKEND_ERROR", "Native helper returned malformed error data.", {"readOnly": not mutating, "writeMayHaveTakenEffect": mutating})
        details = error.get("details") if isinstance(error.get("details"), dict) else {}
        details.setdefault("readOnly", not mutating)
        details.setdefault("writeMayHaveTakenEffect", mutating and error.get("code") in {"NATIVE_ERROR", "WRITE_STATUS_UNKNOWN", "VERIFICATION_FAILED", "ENCODING_ERROR"})
        code = error.get("code", "BACKEND_ERROR")
        if mutating and code == "ENCODING_ERROR":
            details["nativeCode"] = code
            code = "WRITE_STATUS_UNKNOWN"
        raise ToolError(code, error.get("message", "Calendar operation failed."), details)
    if proc.returncode != 0 or not isinstance(response.get("data"), dict):
        raise ToolError("WRITE_STATUS_UNKNOWN" if mutating else "BACKEND_ERROR", "Native helper returned an inconsistent success response.", {"readOnly": not mutating, "writeMayHaveTakenEffect": mutating})
    return response["data"]


def options_for(args):
    options = {}
    for attr, key in (("calendar_id", "calendarId"), ("calendar", "calendar"), ("time_zone", "timeZone"), ("scope", "scope")):
        if getattr(args, attr, None) is not None:
            options[key] = getattr(args, attr)
    if getattr(args, "occurrence", None):
        options["occurrence"] = iso(stamp(args.occurrence, zone(getattr(args, "time_zone", None))))
    return options


def ranges(args, default_days=7, search=False):
    tz = zone(args.time_zone) or local_zone()
    today = datetime.now(tz).date()
    days = args.days if args.days is not None else default_days
    integer(days, "days", minimum=1, maximum=366)
    if args.today and (args.from_date or args.to_date or args.days is not None):
        raise ToolError("INVALID_INPUT", "--today cannot be combined with --from, --to, or --days.")
    start_text = args.from_date or ((today - timedelta(days=30)) if search and args.days is None else today).isoformat()
    start = stamp(start_text, tz)
    if args.today:
        start = stamp(today.isoformat(), tz)
        end = stamp((today + timedelta(days=1)).isoformat(), tz)
    elif args.to_date:
        end = stamp(args.to_date, tz)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.to_date):
            end = stamp((date.fromisoformat(args.to_date) + timedelta(days=1)).isoformat(), tz)
    else:
        end = start + timedelta(days=days)
    if end.timestamp() <= start.timestamp() or end.timestamp() - start.timestamp() > 366 * 86400 + 3600:
        raise ToolError("INVALID_INPUT", "Query range must be positive and at most 366 days.")
    integer(args.limit, "limit", minimum=1, maximum=1000)
    integer(args.offset, "offset", maximum=10000000)
    return {"from": iso(start), "to": iso(end), "limit": args.limit, "offset": args.offset}


def build_parser():
    p = Parser(prog="grok-calendar", description="Apple Desk Calendar: local EventKit, structured JSON, explicit writes.")
    p.add_argument("--json", action="store_true", help="JSON is the default output format")
    p.add_argument("--version", action="version", version=f"grok-calendar {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True, parser_class=Parser)
    def command(name, **kw):
        sp = sub.add_parser(name, **kw); sp.add_argument("--json", action="store_true"); return sp
    def calendar_args(sp):
        sp.add_argument("--calendar", help="exact unique calendar title")
        sp.add_argument("--calendar-id", help="stable EventKit calendar ID")
        sp.add_argument("--time-zone", help="IANA zone for local timestamps")
    def range_args(sp):
        calendar_args(sp)
        sp.add_argument("--from", dest="from_date"); sp.add_argument("--to", dest="to_date", help="date-only is inclusive; timestamp is exclusive")
        sp.add_argument("--days", type=int); sp.add_argument("--today", action="store_true")
        sp.add_argument("--limit", type=int, default=100); sp.add_argument("--offset", type=int, default=0)
        sp.add_argument("--live", action="store_true", help="compatibility: all reads are live")
        sp.add_argument("--light", action="store_true"); sp.add_argument("--all", action="store_true")
        sp.add_argument("--index", type=int, help="legacy read-only calendar index; real ID returned")
    for name in ("doctor", "auth-status", "gaps"):
        command(name)
    sp = command("permissions"); sp.add_argument("operation", choices=["request"])
    sp = command("calendars"); sp.add_argument("--ids", action="store_true"); sp.add_argument("--full", action="store_true")
    sp = command("name-at"); sp.add_argument("--index", type=int, required=True)
    for name in ("list", "events", "search", "free"):
        sp = command(name); range_args(sp)
        if name == "search": sp.add_argument("query")
        if name == "free": sp.add_argument("--duration", default="30m")
    for name in ("show", "read"):
        sp = command(name); sp.add_argument("query", nargs="?"); sp.add_argument("--uid"); sp.add_argument("--occurrence"); range_args(sp)
    for name in ("create", "update"):
        sp = command(name); calendar_args(sp); sp.add_argument("--input")
        for field in ("title", "start", "end", "location", "notes", "url", "availability", "alarms", "recurrence"):
            sp.add_argument("--" + field)
        mode = sp.add_mutually_exclusive_group(); mode.add_argument("--all-day", action="store_true"); mode.add_argument("--timed", action="store_true")
        sp.add_argument("--dry-run", action="store_true")
        if name == "create": sp.add_argument("--idempotency-key")
        else:
            sp.add_argument("target", nargs="?"); sp.add_argument("--uid"); sp.add_argument("--occurrence"); sp.add_argument("--scope", choices=["this", "future"])
    sp = command("delete"); calendar_args(sp); sp.add_argument("target", nargs="?"); sp.add_argument("--uid"); sp.add_argument("--occurrence"); sp.add_argument("--scope", choices=["this", "future"]); sp.add_argument("--force", action="store_true"); sp.add_argument("--dry-run", action="store_true")
    return p


def execute(args):
    command = args.cmd
    if command == "gaps":
        return {"backend": "eventkit", "gaps": ["Meeting invitations and RSVP changes are unsupported; attendees are read-only.", "Verification concerns the local store, not remote account synchronization.", "Offline dry runs do not verify target existence, permissions, recurrence state, or calendar writability.", "Event IDs can change after account synchronization or moves; refresh stale references.", "Mail and Calendar permissions are attributed by macOS to the calling host or signed helper; ad-hoc binary updates may require renewed grants."]}
    if command in {"doctor", "auth-status", "permissions", "calendars"}:
        return native(command)
    if command == "name-at":
        rows = native("calendars")["calendars"]
        if not 0 <= args.index < len(rows):
            raise ToolError("NOT_FOUND", "Calendar index is out of range.")
        return dict(rows[args.index], index=args.index, unstableIndex=True)
    options = options_for(args)
    if command in {"list", "events", "search", "free"}:
        options.update(ranges(args, 180 if command == "search" else 7, command == "search"))
        if args.index is not None:
            if args.calendar or args.calendar_id:
                raise ToolError("INVALID_INPUT", "--index cannot be combined with a calendar name or ID.")
            rows = native("calendars")["calendars"]
            if not 0 <= args.index < len(rows): raise ToolError("NOT_FOUND", "Calendar index is out of range.")
            options["calendarId"] = rows[args.index]["id"]
        options["light"] = args.light
        if command == "search":
            if not args.query.strip(): raise ToolError("INVALID_INPUT", "Search query must be nonempty.")
            options["query"] = args.query
        if command == "free":
            match = re.fullmatch(r"(\d+(?:\.\d+)?)(m|h)?", args.duration)
            if not match: raise ToolError("INVALID_INPUT", "Use a duration such as 30m or 1h.")
            duration = float(match[1]) * (60 if match[2] == "h" else 1)
            if not math.isfinite(duration) or duration <= 0: raise ToolError("INVALID_INPUT", "Duration must be positive.")
            options["durationMinutes"] = duration
        return native("free" if command == "free" else "events", options)
    if command in {"show", "read"}:
        target = args.uid or (args.query if command == "read" else None)
        if target:
            return native("read", options, target=target)
        if not args.query or not args.query.strip(): raise ToolError("INVALID_INPUT", "Supply --uid EVENT or an exact event title.")
        options.update(ranges(args, 180, True)); options.update(exactTitle=args.query, limit=2, offset=0)
        result = native("events", options)
        if result["total"] != 1: raise ToolError("AMBIGUOUS_REFERENCE" if result["total"] else "NOT_FOUND", "Event title did not resolve uniquely. Use an event reference.", {"matches": result["events"]})
        return {"event": result["events"][0]}
    creating = command == "create"
    value = event_input(args, creating) if command in {"create", "update"} else None
    if value and value.get("allDay"):
        options.pop("timeZone", None)
    target = None if creating else (args.uid or args.target)
    if not creating:
        if args.uid and args.target and args.uid != args.target: raise ToolError("INVALID_INPUT", "Conflicting --uid and positional target.")
        validate_reference(target, options)
    if args.dry_run:
        return {"dryRun": True, "action": command, "event": value, "target": target, "options": options, "wouldCreate": creating, "wouldUpdate": command == "update", "wouldDelete": command == "delete", "calendarVerified": False, "targetVerified": False, "message": "Offline validation only. No permission request, calendar access, or mutation occurred."}
    if command == "delete" and not args.force:
        raise ToolError("CONFIRMATION_REQUIRED", "Delete requires --force. Use --dry-run to validate without calendar access.")
    if creating:
        if not args.idempotency_key: raise ToolError("INVALID_INPUT", "Creation requires --idempotency-key to prevent duplicate retries.")
        return StateStore().perform(args.idempotency_key, "calendar.create", {"input": value, "options": options}, lambda: native("create", options, value), preflight=lambda: native("validate-create", options, value))
    with StateStore().locked():
        return native(command, options, value, target)


def main(argv=None):
    try:
        return emit_success(execute(build_parser().parse_args(argv)), tool="grok-calendar")
    except ToolError as exc:
        return emit_error(exc, tool="grok-calendar")
    except (OSError, ValueError, TypeError, OverflowError) as exc:
        return emit_error(ToolError("INVALID_INPUT", str(exc)), tool="grok-calendar")


if __name__ == "__main__":
    raise SystemExit(main())
