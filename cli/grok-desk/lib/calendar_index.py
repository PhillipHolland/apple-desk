"""Fill ~/.cache/grok-calendar via grok-calendar, one index at a time.

Default window is the past 30 days through the next 90 days (inclusive).
Override with grok-desk --past-days / --future-days, or the environment
variables GROK_CALENDAR_PAST_DAYS and GROK_CALENDAR_FUTURE_DAYS (0..366).
A calendar that times out is retried once with a longer limit. A window
that is too wide is split by date. Only the Apple system calendar titled
"Scheduled Reminders" is skipped by name.
"""
from __future__ import annotations

import json
import os
import sys
import signal
import sqlite3
import subprocess
from datetime import date, timedelta

from common import db_path, now_iso, secure_db, secure_dir, which

CACHE = "grok-calendar"
SCHEMA = "3"
SURFACE = "calendar"
AUTH_DENY = {"automation_denied", "calendar_tcc"}
SKIP_CALENDARS = frozenset({"Scheduled Reminders"})
DEFAULT_PAST_DAYS = 30
DEFAULT_FUTURE_DAYS = 90
LIST_LIMIT = 800
FIRST_LIST_TIMEOUT = 50
RETRY_LIST_TIMEOUT = 110
NAME_TIMEOUT = 15
NAME_RETRY_TIMEOUT = 30


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS calendars (
  id TEXT PRIMARY KEY,
  name TEXT,
  writable INTEGER
);
CREATE TABLE IF NOT EXISTS events (
  uid TEXT NOT NULL,
  calendar TEXT,
  title TEXT,
  start_at TEXT NOT NULL,
  end_at TEXT,
  all_day INTEGER,
  PRIMARY KEY (uid, start_at)
);
"""


def _clamp_days(value, default):
    try:
        n = int(value)
    except (TypeError, ValueError):
        return default
    if n < 0:
        return 0
    if n > 366:
        return 366
    return n


def window_days(past_days=None, future_days=None):
    if past_days is None:
        past_days = os.environ.get("GROK_CALENDAR_PAST_DAYS", DEFAULT_PAST_DAYS)
    if future_days is None:
        future_days = os.environ.get("GROK_CALENDAR_FUTURE_DAYS", DEFAULT_FUTURE_DAYS)
    past = _clamp_days(past_days, DEFAULT_PAST_DAYS)
    future = _clamp_days(future_days, DEFAULT_FUTURE_DAYS)
    if future < 1 and past < 1:
        future = 1
    today = date.today()
    start = today - timedelta(days=past)
    end = today + timedelta(days=future)
    return past, future, start, end


def _run(cmd, timeout):
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            proc.kill()
        proc.wait(timeout=2)
        return {"ok": False, "error": "timeout", "code": 4, "message": "exceeded %.0fs" % timeout}
    raw = (stdout or "").strip()
    data = {}
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
    if proc.returncode != 0 or not data.get("ok"):
        err = data.get("error") or ("timeout" if proc.returncode == 4 else "cli_failed")
        message = data.get("message") or (stderr or "").strip()
        return {"ok": False, "error": err, "code": data.get("code", proc.returncode), "message": message[:240]}
    return data


def _pending(reason, called):
    path = db_path(CACHE)
    secure_dir(path.parent)
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA journal_mode=DELETE")
        con.executescript(SCHEMA_SQL)
        con.execute("DELETE FROM events")
        con.execute("DELETE FROM calendars")
        indexed_at = now_iso()
        for key, value in {
            "schema": SCHEMA, "status": "pending_allow", "indexed_at": indexed_at,
            "rows": "0", "calendars": "0", "note": reason[:240],
            "window_from": "", "window_to": "", "skipped_calendars": "0",
            "past_days": "", "future_days": "",
        }.items():
            con.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
        con.commit()
    finally:
        con.close()
        secure_db(path)
    return {"ok": True, "surface": SURFACE, "path": str(path), "status": "pending_allow",
            "rows": 0, "calendars": 0, "indexedAt": indexed_at, "calledApp": called, "message": reason[:240]}


def _store(calendars, events, start, end, past, future, truncated, skipped):
    path = db_path(CACHE)
    secure_dir(path.parent)
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA journal_mode=DELETE")
        con.executescript(SCHEMA_SQL)
        con.execute("DELETE FROM events")
        con.execute("DELETE FROM calendars")
        cal_rows = 0
        for row in calendars:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            ident = str(row.get("id") or name)
            con.execute(
                "INSERT OR REPLACE INTO calendars(id, name, writable) VALUES(?, ?, ?)",
                (ident, name, None),
            )
            cal_rows += 1
        seen = set()
        event_rows = 0
        for row in events:
            title = row.get("title") or ""
            start_at = row.get("start") or ""
            if not start_at:
                continue
            uid = row.get("uid") or "%s|%s|%s" % (row.get("calendar"), start_at, title)
            key = (uid, start_at)
            if key in seen:
                continue
            seen.add(key)
            con.execute(
                "INSERT OR REPLACE INTO events(uid, calendar, title, start_at, end_at, all_day) VALUES(?,?,?,?,?,?)",
                (uid, row.get("calendar") or "", title, start_at, row.get("end") or "", 1 if row.get("allDay") else 0),
            )
            event_rows += 1
        indexed_at = now_iso()
        note = (
            "window past %dd + next %dd; a wide window that times out is read in "
            "14-day slices and each slice is retried once; skip Scheduled Reminders only"
            % (past, future)
        )
        for key, value in {
            "schema": SCHEMA, "status": "ok", "indexed_at": indexed_at,
            "rows": str(event_rows), "calendars": str(cal_rows),
            "window_from": start.isoformat(), "window_to": end.isoformat(),
            "past_days": str(past), "future_days": str(future),
            "truncated": "1" if truncated else "0",
            "skipped_calendars": str(len(skipped)),
            "note": note,
        }.items():
            con.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
        con.commit()
    finally:
        con.close()
        secure_db(path)
    return {
        "ok": True, "surface": SURFACE, "rows": event_rows, "calendars": cal_rows,
        "from": start.isoformat(), "to": end.isoformat(),
        "pastDays": past, "futureDays": future,
        "skipped": skipped, "indexedAt": indexed_at, "calledApp": True,
    }


def _list_once(bin_path, index, start, end, timeout):
    return _run(
        [bin_path, "list", "--live", "--light", "--index", str(index),
         "--from", start.isoformat(), "--to", end.isoformat(),
         "--limit", str(LIST_LIMIT), "--json"],
        timeout,
    )


def _date_slices(start, end, chunk_days):
    cur = start
    while cur <= end:
        nxt = min(cur + timedelta(days=chunk_days - 1), end)
        yield cur, nxt
        cur = nxt + timedelta(days=1)


def _merge(left_status, left_events, left_meta, right_status, right_events, right_meta, start, end, err):
    if left_status == "auth":
        return left_status, [], left_meta
    if right_status == "auth":
        return right_status, [], right_meta
    events = (left_events or []) + (right_events or [])
    if left_status == "ok" or right_status == "ok":
        return "ok", events, {
            "truncated": bool((left_meta or {}).get("truncated") or (right_meta or {}).get("truncated")),
            "split": True,
            "partial": left_status != "ok" or right_status != "ok",
        }
    return "skip", [], {"error": err, "from": start.isoformat(), "to": end.isoformat()}


def _slice_once(bin_path, index, start, end):
    """One slice. A short timeout is retried once longer. No further split."""
    chunk = _list_once(bin_path, index, start, end, 40)
    if chunk.get("error") in AUTH_DENY:
        return "auth", [], chunk
    if chunk.get("ok"):
        return "ok", chunk.get("events") or [], {"truncated": bool(chunk.get("truncated"))}
    err = chunk.get("error") or "list_failed"
    if err == "query_too_broad" and (end - start).days >= 1:
        mid = start + timedelta(days=max(1, ((end - start).days + 1) // 2))
        left_end = mid - timedelta(days=1)
        if left_end >= start:
            return _merge(
                *_slice_once(bin_path, index, start, left_end),
                *_slice_once(bin_path, index, mid, end),
                start, end, err,
            )
    if err in {"timeout", "automation_timeout", "calendar_error"}:
        chunk = _list_once(bin_path, index, start, end, 80)
        if chunk.get("error") in AUTH_DENY:
            return "auth", [], chunk
        if chunk.get("ok"):
            return "ok", chunk.get("events") or [], {"truncated": bool(chunk.get("truncated")), "retried": True}
        err = chunk.get("error") or err
    return "skip", [], {"error": err, "from": start.isoformat(), "to": end.isoformat(), "message": (chunk.get("message") or "")[:160]}


def _events_for_calendar(bin_path, index, start, end):
    # Light calendars answer a full window quickly. A wide window that times out
    # or is too broad is read in 14-day slices instead of one long retry.
    chunk = _list_once(bin_path, index, start, end, 35)
    if chunk.get("error") in AUTH_DENY:
        return "auth", [], chunk
    if chunk.get("ok"):
        return "ok", chunk.get("events") or [], {"truncated": bool(chunk.get("truncated"))}
    err = chunk.get("error") or "list_failed"
    wide = (end - start).days > 14
    if wide and err in {"timeout", "automation_timeout", "calendar_error", "query_too_broad"}:
        events = []
        any_ok = False
        partial = False
        truncated = False
        for a, b in _date_slices(start, end, 14):
            status, got, meta = _slice_once(bin_path, index, a, b)
            if status == "auth":
                return status, [], meta
            if status == "ok":
                any_ok = True
                events.extend(got or [])
                truncated = truncated or bool((meta or {}).get("truncated"))
            else:
                partial = True
        if any_ok:
            return "ok", events, {"truncated": truncated, "split": True, "partial": partial, "retried": True}
        return "skip", [], {"error": err, "from": start.isoformat(), "to": end.isoformat(), "retried": True}
    if err in {"timeout", "automation_timeout", "calendar_error"}:
        chunk = _list_once(bin_path, index, start, end, RETRY_LIST_TIMEOUT)
        if chunk.get("error") in AUTH_DENY:
            return "auth", [], chunk
        if chunk.get("ok"):
            return "ok", chunk.get("events") or [], {"truncated": bool(chunk.get("truncated")), "retried": True}
        err = chunk.get("error") or err
    return "skip", [], {"error": err, "from": start.isoformat(), "to": end.isoformat(), "message": (chunk.get("message") or "")[:160], "retried": True}


def build(past_days=None, future_days=None):
    bin_path = which("grok-calendar")
    if not bin_path:
        return {"ok": False, "error": "missing_cli", "rows": 0, "message": "grok-calendar is not on PATH."}
    past, future, start, end = window_days(past_days, future_days)
    doctor = _run([bin_path, "doctor", "--json"], 30)
    if not doctor.get("ok"):
        if doctor.get("error") in AUTH_DENY or doctor.get("code") in (3, 4) or doctor.get("error") in {"timeout", "automation_timeout"}:
            return _pending(doctor.get("message") or doctor.get("error") or "unauthorized", True)
        return {"ok": False, "error": doctor.get("error") or "doctor_failed", "rows": 0,
                "message": (doctor.get("message") or "doctor failed")[:240]}
    try:
        count = int(doctor.get("calendars") or 0)
    except (TypeError, ValueError):
        count = 0
    calendars = []
    events = []
    skipped = []
    truncated = False
    for i in range(count):
        named = _run([bin_path, "name-at", "--index", str(i), "--json"], NAME_TIMEOUT)
        if not named.get("ok") and named.get("error") in {"timeout", "automation_timeout"}:
            named = _run([bin_path, "name-at", "--index", str(i), "--json"], NAME_RETRY_TIMEOUT)
        if not named.get("ok"):
            if named.get("error") in AUTH_DENY:
                return _pending(named.get("message") or "unauthorized", True)
            skipped.append({"index": i, "error": named.get("error") or "name_failed"})
            continue
        name = (named.get("name") or "").strip()
        if name in SKIP_CALENDARS:
            skipped.append({"index": i, "name": name, "error": "skipped_name"})
            continue
        calendars.append({"id": "index:%d" % i, "name": name, "index": i})
        if os.environ.get("GROK_CALENDAR_PROGRESS"):
            print("calendar %d/%d %s" % (i + 1, count, name), file=sys.stderr, flush=True)
        status, chunk_events, meta = _events_for_calendar(bin_path, i, start, end)
        if os.environ.get("GROK_CALENDAR_PROGRESS"):
            print("  %s events=%d" % (status, len(chunk_events) if status == "ok" else 0), file=sys.stderr, flush=True)
        if status == "auth":
            return _pending((meta or {}).get("message") or "unauthorized", True)
        if status != "ok":
            row = {"index": i, "name": name, "error": (meta or {}).get("error") or "list_failed"}
            if (meta or {}).get("retried"):
                row["retried"] = True
            skipped.append(row)
            continue
        events.extend(chunk_events)
        if (meta or {}).get("truncated"):
            truncated = True
    if not events:
        return {
            "ok": False, "error": "no_events", "rows": 0, "skipped": skipped,
            "from": start.isoformat(), "to": end.isoformat(),
            "pastDays": past, "futureDays": future,
            "message": "no events in the past %dd + next %dd window after skips" % (past, future),
        }
    return _store(calendars, events, start, end, past, future, truncated, skipped)
