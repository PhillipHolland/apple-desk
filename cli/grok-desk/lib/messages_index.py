"""Build ~/.cache/grok-messages/index.sqlite from chat.db, read-only.

Never copies chat.db. Never sends. Group metadata may be stored.
Default build stores chat metadata only. index_bodies stores message text.
That file is as sensitive as Messages when bodies are present.
The send path stays in grok-messages (1:1 unless --chat-guid).
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from common import apple_to_iso, db_path, now_iso, secure_db, secure_dir

CACHE_NAME = "grok-messages"
CHAT_DB = Path.home() / "Library" / "Messages" / "chat.db"
SCHEMA = "1"
BODY_CAP = 8000


def _open_source():
    if not CHAT_DB.exists():
        raise FileNotFoundError(str(CHAT_DB))
    uri = f"file:{CHAT_DB}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    return con


def _open_dest(full: bool) -> sqlite3.Connection:
    path = db_path(CACHE_NAME)
    secure_dir(path.parent)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=DELETE")
    schema = None
    try:
        row = con.execute("SELECT value FROM meta WHERE key='schema'").fetchone()
        if row:
            schema = row[0]
    except sqlite3.OperationalError:
        schema = None
    if full or schema != SCHEMA:
        con.executescript(
            """
            DROP TABLE IF EXISTS message_fts;
            DROP TABLE IF EXISTS chats;
            DROP TABLE IF EXISTS meta;
            """
        )
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
        CREATE TABLE IF NOT EXISTS chats (
          guid TEXT PRIMARY KEY,
          display_name TEXT,
          is_group INTEGER NOT NULL,
          service TEXT,
          last_message_date TEXT,
          message_count INTEGER NOT NULL
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS message_fts USING fts5(
          chat_guid UNINDEXED,
          message_rowid UNINDEXED,
          body,
          tokenize = "unicode61 remove_diacritics 1"
        );
        """
    )
    con.execute(
        "INSERT INTO meta(key, value) VALUES('schema', ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (SCHEMA,),
    )
    return con


def _meta(con: sqlite3.Connection, key: str) -> str | None:
    row = con.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
    return None if row is None else row[0]


def build(full: bool = False, index_bodies: bool = False) -> dict:
    path = db_path(CACHE_NAME)
    try:
        src = _open_source()
    except sqlite3.OperationalError as exc:
        return {
            "ok": False,
            "surface": "messages",
            "error": "needs_full_disk_access",
            "message": "Cannot read ~/Library/Messages/chat.db. Full Disk Access is required. chat.db was not copied.",
            "detail": type(exc).__name__,
        }
    except FileNotFoundError:
        return {
            "ok": False,
            "surface": "messages",
            "error": "no_chat_db",
            "message": "chat.db is not on this Mac.",
        }
    try:
        dest = _open_dest(full)
        chats = src.execute(
            """
            SELECT
              c.guid AS guid,
              c.display_name AS display_name,
              c.service_name AS service,
              c.style AS style,
              (SELECT count(*) FROM chat_message_join j WHERE j.chat_id = c.ROWID) AS message_count,
              (SELECT max(j.message_date) FROM chat_message_join j WHERE j.chat_id = c.ROWID) AS last_date
            FROM chat c
            """
        ).fetchall()
        dest.executemany(
            """
            INSERT INTO chats(guid, display_name, is_group, service, last_message_date, message_count)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(guid) DO UPDATE SET
              display_name=excluded.display_name,
              is_group=excluded.is_group,
              service=excluded.service,
              last_message_date=excluded.last_message_date,
              message_count=excluded.message_count
            """,
            [
                (
                    row["guid"],
                    row["display_name"] or None,
                    1 if row["style"] == 43 else 0,
                    row["service"],
                    apple_to_iso(row["last_date"]),
                    int(row["message_count"] or 0),
                )
                for row in chats
                if row["guid"]
            ],
        )
        added = 0
        if index_bodies:
            if full:
                watermark = 0
            else:
                # Keep rows already stored. A legacy index has no bodies flag.
                fts_count = int(dest.execute("SELECT count(*) FROM message_fts").fetchone()[0] or 0)
                bodies_flag = _meta(dest, "bodies")
                if fts_count == 0 and bodies_flag != "1":
                    watermark = 0
                else:
                    stored = int(_meta(dest, "max_message_rowid") or 0)
                    if stored <= 0 and fts_count:
                        row = dest.execute("SELECT ifnull(max(message_rowid), 0) FROM message_fts").fetchone()
                        stored = int(row[0] or 0)
                    watermark = stored
            texts = src.execute(
                """
                SELECT m.ROWID AS message_rowid, c.guid AS chat_guid, substr(m.text, 1, ?) AS body
                FROM message m
                JOIN chat_message_join cm ON cm.message_id = m.ROWID
                JOIN chat c ON c.ROWID = cm.chat_id
                WHERE m.ROWID > ?
                  AND m.text IS NOT NULL
                  AND length(m.text) > 0
                """,
                (BODY_CAP, watermark),
            )
            max_rowid = watermark
            batch = []
            for row in texts:
                body = row["body"]
                if not body or not row["chat_guid"]:
                    continue
                batch.append((row["chat_guid"], int(row["message_rowid"]), body))
                if int(row["message_rowid"]) > max_rowid:
                    max_rowid = int(row["message_rowid"])
                if len(batch) >= 500:
                    dest.executemany(
                        "INSERT INTO message_fts(chat_guid, message_rowid, body) VALUES (?, ?, ?)",
                        batch,
                    )
                    added += len(batch)
                    batch.clear()
            if batch:
                dest.executemany(
                    "INSERT INTO message_fts(chat_guid, message_rowid, body) VALUES (?, ?, ?)",
                    batch,
                )
                added += len(batch)
            mode = "full" if full or watermark == 0 else "incremental"
        else:
            # Metadata only: do not read message.text. Drop any earlier body copy.
            dest.execute("DELETE FROM message_fts")
            max_rowid = 0
            mode = "metadata"
        chat_count = dest.execute("SELECT count(*) FROM chats").fetchone()[0]
        group_count = dest.execute("SELECT count(*) FROM chats WHERE is_group=1").fetchone()[0]
        fts_count = dest.execute("SELECT count(*) FROM message_fts").fetchone()[0]
        indexed_at = now_iso()
        for key, value in {
            "indexed_at": indexed_at,
            "max_message_rowid": str(max_rowid),
            "mode": mode,
            "bodies": "1" if index_bodies else "0",
            "source": "chat.db-readonly",
        }.items():
            dest.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, value),
            )
        dest.commit()
        if not index_bodies:
            dest.execute("VACUUM")
    except sqlite3.OperationalError as exc:
        return {
            "ok": False,
            "surface": "messages",
            "error": "needs_full_disk_access" if "auth" in str(exc).lower() else "index_failed",
            "message": "Stopped while reading chat.db. It was not copied.",
            "detail": type(exc).__name__,
        }
    finally:
        src.close()
        try:
            dest.close()
        except UnboundLocalError:
            pass
        secure_db(path)
    return {
        "ok": True,
        "surface": "messages",
        "path": str(path),
        "mode": mode,
        "indexBodies": bool(index_bodies),
        "chats": chat_count,
        "groups": group_count,
        "ftsRows": fts_count,
        "ftsAdded": added,
        "indexedAt": indexed_at,
        "copiedChatDb": False,
    }
