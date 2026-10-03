"""Empty calendar and reminders caches. No Apple Events."""
from __future__ import annotations

import sqlite3

from common import db_path, now_iso, secure_db, secure_dir

SCHEMA = "1"


def _write(cache_name: str, table_sql: str) -> dict:
    path = db_path(cache_name)
    secure_dir(path.parent)
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA journal_mode=DELETE")
        existing = None
        try:
            row = con.execute("SELECT value FROM meta WHERE key='status'").fetchone()
            if row:
                existing = row[0]
        except sqlite3.OperationalError:
            existing = None
        con.executescript(table_sql)
        indexed_at = now_iso()
        rows = 0
        # Keep the table empty until Automation Allow exists and a later
        # version fills it from CLI JSON. Do not call the app from here.
        for key, value in {
            "schema": SCHEMA,
            "status": "pending_allow",
            "indexed_at": indexed_at,
            "rows": "0",
            "note": "version-check only; Automation Allow not probed",
        }.items():
            con.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
        con.commit()
        if existing and existing != "pending_allow":
            rows = int(con.execute("SELECT value FROM meta WHERE key='rows'").fetchone()[0] or 0)
    finally:
        con.close()
        secure_db(path)
    return {
        "ok": True,
        "surface": cache_name.removeprefix("grok-"),
        "path": str(path),
        "status": "pending_allow",
        "rows": rows,
        "indexedAt": indexed_at,
        "calledApp": False,
    }


def calendar() -> dict:
    return _write(
        "grok-calendar",
        """
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS events (
          uid TEXT PRIMARY KEY,
          calendar TEXT,
          title TEXT,
          start_at TEXT,
          end_at TEXT,
          all_day INTEGER
        );
        """,
    )


def reminders() -> dict:
    return _write(
        "grok-reminders",
        """
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS reminders (
          id TEXT PRIMARY KEY,
          list_name TEXT,
          title TEXT,
          due TEXT,
          completed INTEGER
        );
        """,
    )
