"""Fill ~/.cache/grok-calendar via grok-calendar, one index at a time."""
from __future__ import annotations

import json
import os
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
WINDOW_DAYS = 14

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


def _store(calendars, events, start, end, truncated, skipped):
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
                "INSERT INTO calendars(id, name, writable) VALUES(?, ?, ?)",
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
                "INSERT INTO events(uid, calendar, title, start_at, end_at, all_day) VALUES(?,?,?,?,?,?)",
                (uid, row.get("calendar") or "", title, start_at, row.get("end") or "", 1 if row.get("allDay") else 0),
            )
            event_rows += 1
        indexed_at = now_iso()
        note = "14-day window via list --index; skipped Scheduled Reminders"
        for key, value in {
            "schema": SCHEMA, "status": "ok", "indexed_at": indexed_at,
            "rows": str(event_rows), "calendars": str(cal_rows),
            "window_from": start, "window_to": end,
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
    return {"ok": True, "surface": SURFACE, "rows": event_rows, "calendars": cal_rows,
            "from": start, "to": end, "skipped": skipped, "indexedAt": indexed_at, "calledApp": True}


def build():
    bin_path = which("grok-calendar")
    if not bin_path:
        return {"ok": False, "error": "missing_cli", "rows": 0, "message": "grok-calendar is not on PATH."}
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
    start = date.today().isoformat()
    end = (date.today() + timedelta(days=WINDOW_DAYS)).isoformat()
    calendars = []
    events = []
    skipped = []
    for i in range(count):
        named = _run([bin_path, "name-at", "--index", str(i), "--json"], 15)
        if not named.get("ok"):
            skipped.append({"index": i, "error": named.get("error") or "name_failed"})
            continue
        name = (named.get("name") or "").strip()
        if name in SKIP_CALENDARS:
            skipped.append({"index": i, "name": name, "error": "skipped_name"})
            continue
        calendars.append({"id": "index:%d" % i, "name": name, "index": i})
        chunk = _run(
            [bin_path, "list", "--live", "--light", "--index", str(i),
             "--from", start, "--to", end, "--limit", "400", "--json"],
            40,
        )
        if chunk.get("error") in AUTH_DENY:
            return _pending(chunk.get("message") or "unauthorized", True)
        if not chunk.get("ok"):
            skipped.append({"index": i, "name": name, "error": chunk.get("error") or "list_failed"})
            continue
        events.extend(chunk.get("events") or [])
    if not events:
        return {"ok": False, "error": "no_events", "rows": 0, "skipped": skipped,
                "message": "no events in the 14-day window after skips"}
    return _store(calendars, events, start, end, False, skipped)
