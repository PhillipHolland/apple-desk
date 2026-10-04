#!/usr/bin/env python3
"""Offline checks for attachments --reveal-path. Uses an in-memory database only."""
from __future__ import annotations

import io
import json
import sqlite3
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

import cli  # noqa: E402
import db  # noqa: E402

STORED = "/tmp/fixture-attachment/photo.jpg"
TILDE = "~/fixture-attachment/photo.jpg"
RELATIVE = "relative/photo.jpg"
CHAT = {
    "rowid": 1,
    "guid": "fixture-chat",
    "name": "Fixture",
    "identifier": "fixture",
    "service": "iMessage",
    "style": "direct",
}


def memory_db():
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        create table attachment (
            ROWID integer primary key,
            mime_type text,
            uti text,
            total_bytes integer,
            is_outgoing integer,
            is_sticker integer,
            transfer_name text,
            created_date integer,
            filename text,
            hide_attachment integer
        );
        create table message_attachment_join (
            attachment_id integer,
            message_id integer
        );
        create table chat_message_join (
            message_id integer,
            chat_id integer
        );
        """
    )
    rows = [
        (1, "image/jpeg", "public.jpeg", 12, 0, 0, "photo.jpg", 0, STORED, 0, 10),
        (2, "image/jpeg", "public.jpeg", 13, 0, 0, "tilde.jpg", 0, TILDE, 0, 11),
        (3, "image/png", "public.png", 14, 0, 0, "rel.png", 0, RELATIVE, 0, 12),
        (4, "image/png", "public.png", 15, 0, 0, "empty.png", 0, None, 0, 13),
    ]
    for row in rows:
        con.execute(
            """
            insert into attachment (
                ROWID, mime_type, uti, total_bytes, is_outgoing, is_sticker,
                transfer_name, created_date, filename, hide_attachment
            ) values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            row[:10],
        )
        con.execute(
            "insert into message_attachment_join (attachment_id, message_id) values (?, ?)",
            (row[0], row[10]),
        )
        con.execute(
            "insert into chat_message_join (message_id, chat_id) values (?, 1)",
            (row[10],),
        )
    return con


def run(argv, con):
    def open_db(_as_json):
        return con

    def resolve(_con, _target, _service, _as_json):
        return dict(CHAT)

    cli.open_db = open_db
    cli._resolve = resolve
    out = io.StringIO()
    err = io.StringIO()
    code = 0
    with redirect_stdout(out), redirect_stderr(err):
        try:
            cli.main(list(argv))
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
    return code, out.getvalue(), err.getvalue()


def main():
    failures = []

    def check(name, cond):
        if cond:
            print("ok", name)
        else:
            failures.append(name)
            print("FAIL", name)

    check("version is 0.2.14", cli.VERSION == "0.2.14")
    check("warning names a private file", "local private file" in cli.PATH_WARNING)
    check("default gaps mention the flag", "--reveal-path" in " ".join(cli.GAPS))

    con = memory_db()
    code, out, err = run(["attachments", "--chat-guid", "fixture-chat", "--json"], con)
    data = json.loads(out)
    check("default exits 0", code == 0 and err == "")
    check("default has no path key", all("path" not in row for row in data["attachments"]))
    check("default json hides the fixture path", STORED not in out and "fixture-attachment" not in out)
    check("default has no reveal warning", "warning" not in data and "revealPath" not in data)
    check("default still names the file", any(row["name"] == "photo.jpg" for row in data["attachments"]))

    con = memory_db()
    code, out, err = run(
        ["attachments", "--chat-guid", "fixture-chat", "--reveal-path", "--json"],
        con,
    )
    data = json.loads(out)
    by_name = {row["name"]: row for row in data["attachments"]}
    home_path = str(Path(TILDE).expanduser())
    check("reveal exits 0", code == 0 and err == "")
    check("reveal warning once in json", data.get("warning") == cli.PATH_WARNING and out.count(cli.PATH_WARNING) == 1)
    check("stored path is printed", by_name["photo.jpg"]["path"] == STORED)
    check("tilde path becomes absolute", by_name["tilde.jpg"]["path"] == home_path and home_path.startswith("/"))
    check("relative path is unavailable", by_name["rel.png"]["path"] is None)
    check("empty path is unavailable", by_name["empty.png"]["path"] is None)
    check("reveal does not claim an open", "opened" not in out.lower() or "nothing was opened" in out.lower())

    con = memory_db()
    code, out, err = run(["attachments", "--chat-guid", "fixture-chat", "--reveal-path"], con)
    check("text warning is one line", out.count(cli.PATH_WARNING) == 1)
    check("text includes stored path", STORED in out)
    check("text says missing path", out.count(cli.PATH_UNAVAILABLE) == 2)
    check("text exits 0", code == 0 and err == "")

    con = memory_db()
    code, out, err = run(["attachments", "--chat-guid", "fixture-chat"], con)
    check("text default omits path", STORED not in out and "fixture-attachment" not in out)
    check("text default has no warning", cli.PATH_WARNING not in out and code == 0)

    if failures:
        print("failed:", ", ".join(failures))
        raise SystemExit(1)
    print("all ok")


if __name__ == "__main__":
    main()
