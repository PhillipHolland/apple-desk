"""Fill ~/.cache/grok-reminders/index.sqlite from Reminders.app (via reminders.js).

Lean doctor + lean lists, then per-list incomplete-only collect. Stores open
reminders (id, list, title, due, completed). Notes are not stored.

Automation deny -> pending_allow. A slow list is skipped; partial indexes stay ok.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from common import db_path, now_iso, secure_db, secure_dir, which

CACHE = "grok-reminders"
SCHEMA = "3"
SURFACE = "reminders"
AUTH_DENY = {"automation_denied"}

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
    blob = (proc.stderr or "") + "\n" + raw
    if proc.returncode in (142, -14) or "Alarm clock" in blob:
        return {"ok": False, "error": "timeout", "code": 4, "message": "exceeded alarm"}
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


def _reminders_js() -> Path | None:
    bin_path = which("grok-reminders")
    if not bin_path:
        return None
    js = Path(bin_path).resolve().parent.parent / "lib" / "reminders.js"
    return js if js.is_file() else None


def _jxa(payload: dict, alarm: int) -> dict:
    js = _reminders_js()
    if js is None:
        return {"ok": False, "error": "missing_cli", "message": "reminders.js was not found"}
    cmd = [
        "perl", "-e", "alarm shift @ARGV; exec @ARGV", str(alarm),
        "osascript", "-l", "JavaScript", str(js), "--", json.dumps(payload),
    ]
    return _run(cmd, alarm + 5)


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
    doctor = _jxa({"op": "doctor"}, 15)
    if not doctor.get("ok"):
        if doctor.get("error") in AUTH_DENY or doctor.get("error") == "automation_timeout":
            return _pending(doctor.get("message") or doctor.get("error") or "unauthorized", True)
        if doctor.get("error") == "timeout":
            return _pending(doctor.get("message") or "doctor timed out", True)
        return {
            "ok": False,
            "surface": SURFACE,
            "error": doctor.get("error") or "doctor_failed",
            "status": "error",
            "rows": 0,
            "calledApp": True,
            "message": (doctor.get("message") or "grok-reminders doctor failed")[:240],
        }

    lists = _jxa({"op": "lists", "counts": False}, 20)
    if not lists.get("ok"):
        if lists.get("error") in AUTH_DENY:
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

    list_rows_meta = list(lists.get("lists") or [])
    collected: list[dict] = []
    skipped: list[str] = []
    for row in list_rows_meta:
        name = (row.get("name") or "").strip()
        if not name:
            continue
        # Per-list incomplete collect. One slow list must not fail the whole index.
        piece = _jxa(
            {"op": "collect", "list": name, "withBody": False, "incompleteOnly": True, "cap": 2000},
            35,
        )
        if piece.get("error") in AUTH_DENY:
            return _pending(piece.get("message") or piece.get("error") or "unauthorized", True)
        if not piece.get("ok"):
            skipped.append(name)
            continue
        collected.extend(piece.get("reminders") or [])

    path = db_path(CACHE)
    secure_dir(path.parent)
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA journal_mode=DELETE")
        con.executescript(SCHEMA_SQL)
        con.execute("DELETE FROM reminders")
        con.execute("DELETE FROM lists")
        list_rows = 0
        for row in list_rows_meta:
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
        for row in collected:
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
        status = "ok" if reminder_rows or list_rows else "ok"
        meta = {
            "schema": SCHEMA,
            "status": status,
            "indexed_at": indexed_at,
            "rows": str(reminder_rows),
            "lists": str(list_rows),
            "skipped_lists": str(len(skipped)),
            "note": "incomplete reminders only; no notes; per-list collect",
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
        "status": status,
        "rows": reminder_rows,
        "lists": list_rows,
        "skippedLists": len(skipped),
        "skipped": skipped,
        "indexedAt": indexed_at,
        "calledApp": True,
    }
