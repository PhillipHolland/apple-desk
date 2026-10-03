"""Fill ~/.cache/grok-reminders/index.sqlite from grok-reminders.

One doctor. If it is authorized, store list names plus incomplete reminders
due today through 60 days (the CLI maximum): id, list, title, due, completed.
Notes are not stored. A timeout or a denied Automation grant is pending_allow
and is not retried in this process.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess

from common import db_path, now_iso, secure_db, secure_dir, which

CACHE = "grok-reminders"
SCHEMA = "2"
SURFACE = "reminders"
AUTH = {"timeout", "automation_timeout", "automation_denied"}
DAYS = 60

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS lists (
  id TEXT PRIMARY KEY,
  name TEXT,
  incomplete INTEGER,
  total INTEGER
);
CREATE TABLE IF NOT EXISTS reminders (
  id TEXT PRIMARY KEY,
  list_name TEXT,
  title TEXT,
  due TEXT,
  completed INTEGER
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
        con.execute("DELETE FROM reminders")
        con.execute("DELETE FROM lists")
        indexed_at = now_iso()
        meta = {
            "schema": SCHEMA,
            "status": "pending_allow",
            "indexed_at": indexed_at,
            "rows": "0",
            "lists": "0",
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
        "lists": 0,
        "indexedAt": indexed_at,
        "calledApp": called,
        "message": reason[:240],
    }


def build() -> dict:
    bin_path = which("grok-reminders")
    if not bin_path:
        return {
            "ok": False,
            "surface": SURFACE,
            "error": "missing_cli",
            "status": "pending_allow",
            "rows": 0,
            "calledApp": False,
            "message": "grok-reminders is not on PATH.",
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
            "message": (doctor.get("message") or "grok-reminders doctor failed")[:240],
        }
    lists = _run([bin_path, "lists", "--json"], 28)
    if not lists.get("ok"):
        if lists.get("error") in AUTH or lists.get("code") in (3, 4):
            return _pending(lists.get("message") or lists.get("error") or "unauthorized", True)
        return {
            "ok": False,
            "surface": SURFACE,
            "error": lists.get("error") or "lists_failed",
            "status": "error",
            "rows": 0,
            "calledApp": True,
            "message": (lists.get("message") or "grok-reminders lists failed")[:240],
        }
    upcoming = _run([bin_path, "upcoming", "--days", str(DAYS), "--json"], 40)
    if not upcoming.get("ok"):
        if upcoming.get("error") in AUTH or upcoming.get("code") in (3, 4):
            return _pending(upcoming.get("message") or upcoming.get("error") or "unauthorized", True)
        return {
            "ok": False,
            "surface": SURFACE,
            "error": upcoming.get("error") or "upcoming_failed",
            "status": "error",
            "rows": 0,
            "calledApp": True,
            "message": (upcoming.get("message") or "grok-reminders upcoming failed")[:240],
        }

    path = db_path(CACHE)
    secure_dir(path.parent)
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA journal_mode=DELETE")
        con.executescript(SCHEMA_SQL)
        con.execute("DELETE FROM reminders")
        con.execute("DELETE FROM lists")
        list_rows = 0
        for row in lists.get("lists") or []:
            name = (row.get("name") or "").strip()
            if not name:
                continue
            ident = str(row.get("id") or name)
            con.execute(
                "INSERT INTO lists(id, name, incomplete, total) VALUES(?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, incomplete=excluded.incomplete, total=excluded.total",
                (ident, name, int(row.get("incomplete") or 0), int(row.get("reminders") or 0)),
            )
            list_rows += 1
        reminder_rows = 0
        seen = set()
        for row in upcoming.get("reminders") or []:
            ident = str(row.get("id") or "")
            if not ident or ident in seen:
                continue
            seen.add(ident)
            con.execute(
                "INSERT INTO reminders(id, list_name, title, due, completed) VALUES(?, ?, ?, ?, ?)",
                (
                    ident,
                    row.get("list") or "",
                    row.get("title") or "",
                    row.get("due") or "",
                    1 if row.get("completed") else 0,
                ),
            )
            reminder_rows += 1
        indexed_at = now_iso()
        meta = {
            "schema": SCHEMA,
            "status": "ok",
            "indexed_at": indexed_at,
            "rows": str(reminder_rows),
            "lists": str(list_rows),
            "window_from": str(upcoming.get("from") or ""),
            "window_to": str(upcoming.get("to") or ""),
            "days": str(DAYS),
            "note": "list names plus due reminders; no notes",
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
        "status": "ok",
        "rows": reminder_rows,
        "lists": list_rows,
        "from": upcoming.get("from"),
        "to": upcoming.get("to"),
        "days": DAYS,
        "indexedAt": indexed_at,
        "calledApp": True,
    }
