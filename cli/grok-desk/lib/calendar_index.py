"""Fill ~/.cache/grok-calendar/index.sqlite from grok-calendar.

One doctor. If it is authorized, store calendar names and events from today
through 90 days: uid, title, start, end, all-day, calendar name. No locations,
no notes. A timeout or a denied Automation grant is pending_allow and is not
retried in this process.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from datetime import date, timedelta

from common import db_path, now_iso, secure_db, secure_dir, which

CACHE = "grok-calendar"
SCHEMA = "2"
SURFACE = "calendar"
AUTH = {"timeout", "automation_timeout", "automation_denied", "calendar_tcc"}

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


def _run(cmd: list[str], timeout: float) -> dict:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "code": 4, "message": f"exceeded {timeout:.0f}s"}
    raw = (proc.stdout or "").strip()
    data: dict = {}
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = {}
    if proc.returncode != 0 or not data.get("ok"):
        err = data.get("error")
        if not err:
            err = "timeout" if proc.returncode == 4 else "cli_failed"
        message = data.get("message") or (proc.stderr or "").strip()
        return {
            "ok": False,
            "error": err,
            "code": data.get("code", proc.returncode),
            "message": message[:240],
        }
    return data


def _pending(reason: str, called: bool) -> dict:
    path = db_path(CACHE)
    secure_dir(path.parent)
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA journal_mode=DELETE")
        con.executescript(SCHEMA_SQL)
        con.execute("DELETE FROM events")
        con.execute("DELETE FROM calendars")
        indexed_at = now_iso()
        meta = {
            "schema": SCHEMA,
            "status": "pending_allow",
            "indexed_at": indexed_at,
            "rows": "0",
            "calendars": "0",
            "note": reason[:240],
        }
        for key, value in meta.items():
            con.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
        con.commit()
    finally:
        con.close()
        secure_db(path)
    return {
        "ok": True,
        "surface": SURFACE,
        "path": str(path),
        "status": "pending_allow",
        "rows": 0,
        "calendars": 0,
        "indexedAt": indexed_at,
        "calledApp": called,
        "message": reason[:240],
    }


def _window() -> tuple[str, str]:
    start = date.today()
    end = start + timedelta(days=90)
    return start.isoformat(), end.isoformat()


def _events_for(bin_path: str, start: str, end: str, calendar: str | None) -> dict:
    cmd = [bin_path, "list", "--from", start, "--to", end, "--limit", "800", "--json"]
    if calendar:
        cmd[2:2] = ["--calendar", calendar]
    return _run(cmd, 40)


DENIED = {"automation_denied", "calendar_tcc"}
SLOW = {"timeout", "automation_timeout", "query_too_broad"}


def _slices(start: str, end: str):
    cursor = date.fromisoformat(start)
    stop = date.fromisoformat(end)
    while cursor <= stop:
        slice_end = min(cursor + timedelta(days=29), stop)
        yield cursor.isoformat(), slice_end.isoformat()
        cursor = slice_end + timedelta(days=1)


def _one_calendar(bin_path: str, start: str, end: str, name: str) -> tuple[list[dict], bool, str | None]:
    """One 90-day read. A slow or too-broad read is split into 30-day slices once.

    A denied Automation error is raised. A slice that still times out is not retried.
    """
    chunk = _events_for(bin_path, start, end, name)
    if chunk.get("ok"):
        return list(chunk.get("events") or []), bool(chunk.get("truncated")), None
    if chunk.get("error") in DENIED:
        raise _Auth(chunk)
    if chunk.get("error") not in SLOW:
        return [], False, name
    events: list[dict] = []
    truncated = False
    for slice_start, slice_end in _slices(start, end):
        piece = _events_for(bin_path, slice_start, slice_end, name)
        if piece.get("error") in DENIED:
            raise _Auth(piece)
        if not piece.get("ok"):
            return [], False, name
        events.extend(piece.get("events") or [])
        truncated = truncated or bool(piece.get("truncated"))
    return events, truncated, None


def _collect_events(bin_path: str, start: str, end: str, names: list[str]) -> tuple[list[dict], bool, list[str]]:
    """Per calendar. A single 90-day read of every calendar exceeds grok-calendar's 25s cap."""
    events: list[dict] = []
    truncated = False
    skipped: list[str] = []
    for name in names:
        rows, cut, skip = _one_calendar(bin_path, start, end, name)
        if skip:
            skipped.append(skip)
            continue
        events.extend(rows)
        truncated = truncated or cut
    return events, truncated, skipped


class _Auth(Exception):
    def __init__(self, payload: dict):
        super().__init__(payload.get("error") or "unauthorized")
        self.payload = payload


class _Fail(Exception):
    def __init__(self, payload: dict):
        super().__init__(payload.get("error") or "cli_failed")
        self.payload = payload


def _store(calendars: list[dict], events: list[dict], start: str, end: str, truncated: bool, skipped: list[str]) -> dict:
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
            ident = row.get("id") or name
            con.execute(
                "INSERT INTO calendars(id, name, writable) VALUES(?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, writable=excluded.writable",
                (str(ident), name, 1 if row.get("writable") else 0),
            )
            cal_rows += 1
        seen = set()
        event_rows = 0
        for row in events:
            title = row.get("title") or ""
            start_at = row.get("start") or ""
            uid = row.get("uid") or f"{row.get('calendar')}|{start_at}|{title}"
            key = (uid, start_at)
            if key in seen or not start_at:
                continue
            seen.add(key)
            con.execute(
                "INSERT INTO events(uid, calendar, title, start_at, end_at, all_day) VALUES(?, ?, ?, ?, ?, ?)",
                (
                    uid,
                    row.get("calendar") or "",
                    title,
                    start_at,
                    row.get("end") or "",
                    1 if row.get("allDay") else 0,
                ),
            )
            event_rows += 1
        indexed_at = now_iso()
        meta = {
            "schema": SCHEMA,
            "status": "ok",
            "indexed_at": indexed_at,
            "rows": str(event_rows),
            "calendars": str(cal_rows),
            "window_from": start,
            "window_to": end,
            "truncated": "1" if truncated else "0",
            "skipped_calendars": str(len(skipped)),
            "note": "titles, times, uids, calendar names only",
        }
        for key, value in meta.items():
            con.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
        con.commit()
    finally:
        con.close()
        secure_db(path)
    out = {
        "ok": True,
        "surface": SURFACE,
        "path": str(path),
        "status": "ok",
        "rows": event_rows,
        "calendars": cal_rows,
        "from": start,
        "to": end,
        "truncated": truncated,
        "skippedCalendars": len(skipped),
        "indexedAt": indexed_at,
        "calledApp": True,
    }
    return out


def build() -> dict:
    bin_path = which("grok-calendar")
    if not bin_path:
        return {
            "ok": False,
            "surface": SURFACE,
            "error": "missing_cli",
            "status": "pending_allow",
            "rows": 0,
            "calledApp": False,
            "message": "grok-calendar is not on PATH.",
        }
    doctor = _run([bin_path, "doctor", "--json"], 28)
    if not doctor.get("ok"):
        if doctor.get("error") in AUTH or doctor.get("code") in (3, 4):
            return _pending(doctor.get("message") or doctor.get("error") or "unauthorized", True)
        return {
            "ok": False,
            "surface": SURFACE,
            "error": doctor.get("error") or "doctor_failed",
            "status": "error",
            "rows": 0,
            "calledApp": True,
            "message": (doctor.get("message") or "grok-calendar doctor failed")[:240],
        }
    listed = _run([bin_path, "calendars", "--json"], 28)
    if not listed.get("ok"):
        if listed.get("error") in AUTH or listed.get("code") in (3, 4):
            return _pending(listed.get("message") or listed.get("error") or "unauthorized", True)
        return {
            "ok": False,
            "surface": SURFACE,
            "error": listed.get("error") or "calendars_failed",
            "status": "error",
            "rows": 0,
            "calledApp": True,
            "message": (listed.get("message") or "grok-calendar calendars failed")[:240],
        }
    calendars = list(listed.get("calendars") or [])
    names = [row.get("name") for row in calendars if row.get("name")]
    start, end = _window()
    try:
        events, truncated, skipped = _collect_events(bin_path, start, end, names)
    except _Auth as exc:
        return _pending(exc.payload.get("message") or exc.payload.get("error") or "unauthorized", True)
    except _Fail as exc:
        return {
            "ok": False,
            "surface": SURFACE,
            "error": exc.payload.get("error") or "list_failed",
            "status": "error",
            "rows": 0,
            "calledApp": True,
            "message": (exc.payload.get("message") or "grok-calendar list failed")[:240],
        }
    if names and not events and len(skipped) == len(names):
        return _pending("every calendar list timed out or was refused; not retried", True)
    return _store(calendars, events, start, end, truncated, skipped)
