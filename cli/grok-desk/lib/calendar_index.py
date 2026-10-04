"""Bounded EventKit reads into an explicitly dated, private local calendar index.

No permission requests are made here. Native IDs, occurrence references, exact
start/end values and time zones are retained. Failed attempts never look fresh.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import common

CACHE = "grok-calendar"
SCHEMA = "4"
SURFACE = "calendar"
DEFAULT_PAST_DAYS = 30
DEFAULT_FUTURE_DAYS = 90
LIST_LIMIT = 800
MAX_PAGES_PER_WINDOW = 100
MAX_AGE_SECONDS = 86400
SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE calendars (id TEXT PRIMARY KEY, name TEXT NOT NULL, writable INTEGER);
CREATE TABLE events (
  uid TEXT NOT NULL, calendar_id TEXT NOT NULL, calendar TEXT NOT NULL,
  title TEXT, start_at TEXT NOT NULL, end_at TEXT NOT NULL, all_day INTEGER NOT NULL,
  time_zone TEXT NOT NULL, reference TEXT, occurrence TEXT NOT NULL,
  start_epoch REAL NOT NULL, end_epoch REAL NOT NULL,
  PRIMARY KEY(calendar_id, uid, start_at, occurrence)
);
CREATE INDEX events_overlap ON events(start_epoch, end_epoch);
"""


def _clamp_days(value, default):
    try:
        return max(0, min(366, int(value)))
    except (TypeError, ValueError):
        return default


def window_days(past_days=None, future_days=None):
    past = _clamp_days(os.environ.get("GROK_CALENDAR_PAST_DAYS", DEFAULT_PAST_DAYS) if past_days is None else past_days, DEFAULT_PAST_DAYS)
    future = _clamp_days(os.environ.get("GROK_CALENDAR_FUTURE_DAYS", DEFAULT_FUTURE_DAYS) if future_days is None else future_days, DEFAULT_FUTURE_DAYS)
    today = date.today()
    # The requested final calendar day is included; the stored upper bound is exclusive.
    return past, future, today - timedelta(days=past), today + timedelta(days=future + 1)


def _midnight(day):
    # astimezone on each local date applies that date's system DST rules.
    return datetime.combine(day, datetime.min.time()).astimezone()


def _instant(value, zone=None):
    if not isinstance(value, str) or not value:
        raise ValueError("An event/query timestamp is missing.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        if len(value) != 10 or zone is None:
            raise ValueError("Timed events require an explicit UTC offset; all-day dates require a time zone.")
        parsed = parsed.replace(tzinfo=ZoneInfo(zone))
    return parsed.timestamp()


def _run(cmd, timeout):
    result = common.run_cmd(cmd, timeout, stdout_limit=8 * 1024 * 1024)
    return common.unwrap_result(result)


def _meta(con):
    try:
        return dict(con.execute("SELECT key, value FROM meta"))
    except sqlite3.Error:
        return {}


def _set_meta(con, values):
    for key, value in values.items():
        con.execute("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, str(value)))


def _record_failure(error, message, called):
    """Keep any old snapshot, but mark the unsuccessful refresh explicitly."""
    path = common.db_path(CACHE)
    common.secure_dir(path.parent)
    con = sqlite3.connect(path)
    try:
        con.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
        old = _meta(con)
        status = "stale" if old.get("indexed_at") else "unavailable"
        _set_meta(con, {"status": status, "last_attempt_at": common.now_iso(), "last_error": error,
                        "last_error_message": message[:240]})
        con.commit()
    finally:
        con.close()
        common.secure_db(path)
    return {"ok": False, "surface": SURFACE, "path": str(path), "status": status,
            "error": error, "message": message[:240], "calledApp": called, "retainedPrevious": bool(old.get("indexed_at"))}


def _event(row, calendar):
    if not isinstance(row, dict):
        raise ValueError("Calendar returned a non-object event.")
    ident = row.get("id") or row.get("uid")
    calendar_id = row.get("calendarId")
    start, end, zone, all_day = row.get("start"), row.get("end"), row.get("timeZone"), row.get("allDay")
    if not isinstance(ident, str) or not ident or calendar_id != calendar["id"]:
        raise ValueError("Calendar returned an event without its actual event/calendar identity.")
    if not isinstance(zone, str) or not zone or not isinstance(all_day, bool):
        raise ValueError("Calendar returned an event without its time zone or all-day type.")
    if all_day and (not isinstance(start, str) or len(start) != 10 or not isinstance(end, str) or len(end) != 10):
        raise ValueError("All-day events require date-only start and exclusive end.")
    start_epoch, end_epoch = _instant(start, zone if all_day else None), _instant(end, zone if all_day else None)
    if end_epoch < start_epoch or (all_day and end_epoch == start_epoch):
        raise ValueError("Calendar returned an invalid event end.")
    return (ident, calendar_id, calendar["name"], str(row.get("title") or ""), start, end, int(all_day), zone,
            row.get("reference") or row.get("ref"), str(row.get("occurrence") or ""), start_epoch, end_epoch)


def _store(calendars, events, start, end, past, future, failures):
    path = common.db_path(CACHE)
    common.secure_dir(path.parent)
    con = sqlite3.connect(path, timeout=10)
    try:
        con.executescript("BEGIN IMMEDIATE; DROP TABLE IF EXISTS events; DROP TABLE IF EXISTS calendars;\n" + SCHEMA_SQL)
        for cal in calendars:
            con.execute("INSERT INTO calendars(id,name,writable) VALUES(?,?,?)", (cal["id"], cal["name"], int(cal["writable"])))
        con.executemany("INSERT OR REPLACE INTO events VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", events)
        rows = con.execute("SELECT count(*) FROM events").fetchone()[0]
        indexed_at = common.now_iso()
        status = "partial" if failures else "ok"
        con.execute("DELETE FROM meta")
        _set_meta(con, {"schema": SCHEMA, "status": status, "indexed_at": indexed_at, "last_attempt_at": indexed_at,
                       "rows": rows, "calendars": len(calendars), "window_from": start.isoformat(), "window_to": end.isoformat(),
                       "window_start_epoch": start.timestamp(), "window_end_epoch": end.timestamp(),
                       "past_days": past, "future_days": future, "partial": int(bool(failures)),
                       "failures": json.dumps(failures), "source": "eventkit", "max_age_seconds": MAX_AGE_SECONDS})
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()
        common.secure_db(path)
    return {"ok": not failures, "surface": SURFACE, "path": str(path), "status": status,
            "rows": rows, "calendars": len(calendars), "from": start.isoformat(), "to": end.isoformat(),
            "endExclusive": True, "pastDays": past, "futureDays": future, "partial": bool(failures),
            "failures": failures, "indexedAt": indexed_at, "calledApp": True,
            "error": "index_partial" if failures else None}


def build(past_days=None, future_days=None):
    binary = common.which("grok-calendar")
    if not binary:
        return _record_failure("missing_cli", "grok-calendar is not installed.", False)
    doctor = _run([binary, "doctor", "--json"], 8)
    auth = doctor.get("data") or {}
    if not doctor.get("ok"):
        return _record_failure(doctor.get("error") or "doctor_failed", doctor.get("message") or "Calendar diagnostics are unavailable.", True)
    if auth.get("authorization") != "fullAccess" or auth.get("fullAccess") is not True:
        status = auth.get("authorization") or "unknown"
        return _record_failure("permission_required" if status in {"denied", "restricted", "notDetermined", "writeOnly"} else "authorization_unknown",
                               "Calendar full access is not confirmed (" + str(status) + "). Use explicit Calendar permission setup.", True)
    listed = _run([binary, "calendars", "--json"], 20)
    raw_calendars = (listed.get("data") or {}).get("calendars")
    if not listed.get("ok") or not isinstance(raw_calendars, list):
        return _record_failure(listed.get("error") or "invalid_response", listed.get("message") or "Calendar discovery returned no valid calendar list.", True)
    calendars = []
    for row in raw_calendars:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str) or not row["id"]:
            return _record_failure("invalid_response", "Calendar discovery omitted a real calendar ID.", True)
        calendars.append({"id": row["id"], "name": str(row.get("title") or row.get("name") or ""), "writable": row.get("writable") is True})
    if len({cal["id"] for cal in calendars}) != len(calendars):
        return _record_failure("invalid_response", "Calendar discovery returned duplicate calendar IDs.", True)
    past, future, first_day, last_day = window_days(past_days, future_days)
    start, end = _midnight(first_day), _midnight(last_day)
    events, failures = [], []
    for calendar in calendars:
        day = first_day
        while day < last_day:
            next_day = min(day + timedelta(days=31), last_day)
            lower, upper = _midnight(day), _midnight(next_day)
            offset = 0
            expected_total, seen = None, set()
            for _ in range(MAX_PAGES_PER_WINDOW):
                chunk = _run([binary, "list", "--live", "--light", "--calendar-id", calendar["id"],
                              "--from", lower.isoformat(), "--to", upper.isoformat(), "--limit", str(LIST_LIMIT),
                              "--offset", str(offset), "--json"], 45)
                data = chunk.get("data") or {}
                raw_events = data.get("events")
                failure = None
                if not chunk.get("ok") or not isinstance(raw_events, list):
                    failure = chunk.get("error") or "invalid_response"
                else:
                    try:
                        for row in raw_events:
                            event = _event(row, calendar)
                            lo, hi = event[-2:]
                            if not ((lo < upper.timestamp() and hi > lower.timestamp()) or
                                    (lo == hi and lower.timestamp() <= lo < upper.timestamp())):
                                raise ValueError("An event does not overlap its requested window.")
                            identity = (event[0], event[1], event[4], event[9])
                            if identity in seen:
                                raise ValueError("Calendar pagination repeated an event occurrence.")
                            seen.add(identity)
                            events.append(event)
                    except (ValueError, TypeError, ZoneInfoNotFoundError):
                        failure = "invalid_event"
                    total = data.get("total")
                    if (not isinstance(data.get("truncated"), bool) or not isinstance(total, int) or isinstance(total, bool)
                            or total < offset + len(raw_events) or data.get("offset") != offset
                            or data.get("truncated") != (offset + len(raw_events) < total)):
                        failure = failure or "invalid_pagination"
                    elif expected_total is not None and total != expected_total:
                        failure = failure or "calendar_changed_during_index"
                    else:
                        expected_total = total
                    if data.get("partial") is True:
                        failure = failure or "partial_response"
                if failure:
                    failures.append({"calendarId": calendar["id"], "from": lower.isoformat(), "to": upper.isoformat(), "offset": offset, "error": failure})
                    break
                truncated = data.get("truncated") is True
                if not truncated:
                    break
                if not raw_events or len(raw_events) > LIST_LIMIT or data.get("offset", offset) != offset:
                    failures.append({"calendarId": calendar["id"], "error": "invalid_pagination", "offset": offset})
                    break
                offset += len(raw_events)
            else:
                failures.append({"calendarId": calendar["id"], "error": "page_limit", "offset": offset})
            day = next_day
    return _store(calendars, events, start, end, past, future, failures)


def cache_status():
    path = common.db_path(CACHE)
    if not path.exists():
        return {"status": "missing", "stale": True, "complete": False, "path": str(path)}
    try:
        with closing(sqlite3.connect(f"file:{path}?mode=ro", uri=True)) as con:
            meta = _meta(con)
        indexed_at = meta.get("indexed_at")
        age = datetime.now(timezone.utc).timestamp() - _instant(indexed_at) if indexed_at else None
        stale = age is None or age < -300 or age > MAX_AGE_SECONDS or meta.get("status") == "stale"
        compatible = meta.get("schema") == SCHEMA
        complete = compatible and meta.get("status") == "ok" and meta.get("partial") == "0"
        status = "unavailable" if not indexed_at else ("schema_mismatch" if not compatible else ("stale" if stale else meta.get("status", "unavailable")))
        return {"status": status, "stale": stale, "complete": complete, "path": str(path), "meta": meta,
                "indexedAt": indexed_at, "ageSeconds": age, "maxAgeSeconds": MAX_AGE_SECONDS,
                "windowFrom": meta.get("window_from"), "windowTo": meta.get("window_to")}
    except (sqlite3.Error, ValueError, TypeError):
        return {"status": "unreadable", "stale": True, "complete": False, "path": str(path)}


def cached_search(query, limit, start=None, end=None, calendar_id=None):
    if not isinstance(limit, int) or not 1 <= limit <= 1000:
        return {"ok": False, "error": "invalid_limit", "message": "--limit must be 1..1000."}
    info = cache_status()
    if info["status"] in {"missing", "unreadable", "schema_mismatch", "unavailable"}:
        return {"ok": False, "error": info["status"], "message": "Calendar cache is unavailable; run an explicit calendar reindex.", "cache": info}
    clauses, args = ["title LIKE ? ESCAPE '\\' COLLATE NOCASE"], ["%" + query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"]
    try:
        if (start is None) != (end is None):
            raise ValueError("Pass both --from and --to.")
        if start is not None:
            lower, upper = _instant(start), _instant(end)
            if lower >= upper:
                raise ValueError("--from must precede the exclusive --to.")
            if lower < float(info["meta"]["window_start_epoch"]) or upper > float(info["meta"]["window_end_epoch"]):
                return {"ok": False, "error": "cache_window_miss", "message": "The requested window extends beyond the cached window.", "cache": info}
            clauses.append("((start_epoch < ? AND end_epoch > ?) OR (start_epoch=end_epoch AND start_epoch>=? AND start_epoch<?))")
            args.extend([upper, lower, lower, upper])
        if calendar_id:
            clauses.append("calendar_id=?")
            args.append(calendar_id)
        with closing(sqlite3.connect(f"file:{info['path']}?mode=ro", uri=True)) as con:
            rows = list(con.execute("SELECT uid,calendar_id,calendar,title,start_at,end_at,all_day,time_zone,reference,occurrence FROM events WHERE " + " AND ".join(clauses) + " ORDER BY start_epoch,calendar_id,uid LIMIT ?", args + [limit + 1]))
        hits = [{"id": r[0], "uid": r[0], "calendarId": r[1], "calendar": r[2], "title": r[3], "start": r[4], "end": r[5], "allDay": bool(r[6]), "timeZone": r[7], "reference": r[8], "occurrence": r[9] or None} for r in rows[:limit]]
    except (sqlite3.Error, ValueError, TypeError, KeyError) as exc:
        return {"ok": False, "error": "invalid_cache_query", "message": str(exc)[:200]}
    ok = info["complete"] and not info["stale"]
    return {"ok": ok, "error": None if ok else ("cache_stale" if info["stale"] else "cache_partial"),
            "surface": SURFACE, "source": "cache", "query": query, "hits": hits, "count": len(hits),
            "truncated": len(rows) > limit, "partial": not info["complete"] or len(rows) > limit,
            "stale": info["stale"], "cacheComplete": info["complete"], "path": info["path"],
            "indexedAt": info["indexedAt"], "windowFrom": info["windowFrom"], "windowTo": info["windowTo"], "endExclusive": True}
