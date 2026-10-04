#!/usr/bin/env python3
"""Offline metadata reindex. Does not read or write the live ~/.cache indexes."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

REAL_HOME = os.environ.get("HOME", "")
ROOT = Path(tempfile.mkdtemp(prefix="grok-desk-meta-", dir="/tmp"))
os.environ["HOME"] = str(ROOT / "home")
(ROOT / "home").mkdir()
os.environ["GROK_DESK_NO_TELEMETRY"] = "1"

LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

import cli  # noqa: E402
import messages_index  # noqa: E402

SECRET = "secret-message-body"
SECRET_2 = "secret-message-body-2"


def chat_db():
    path = messages_index.CHAT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def write_source(rows, with_messages):
    path = chat_db()
    if path.exists():
        path.unlink()
    con = sqlite3.connect(path)
    con.execute(
        "CREATE TABLE chat (ROWID INTEGER PRIMARY KEY, guid TEXT, display_name TEXT, service_name TEXT, style INTEGER)"
    )
    con.execute("CREATE TABLE chat_message_join (chat_id INTEGER, message_id INTEGER, message_date INTEGER)")
    con.execute("INSERT INTO chat VALUES (1, 'iMessage;-;fixture', 'Fixture', 'iMessage', 45)")
    if with_messages:
        con.execute("CREATE TABLE message (ROWID INTEGER PRIMARY KEY, text TEXT)")
        for rowid, text in rows:
            con.execute("INSERT INTO message VALUES (?, ?)", (rowid, text))
            con.execute("INSERT INTO chat_message_join VALUES (1, ?, 100)", (rowid,))
    else:
        con.execute("INSERT INTO chat_message_join VALUES (1, 1, 100)")
    con.commit()
    con.close()
    return path


def fts_bodies():
    con = sqlite3.connect(messages_index.db_path(messages_index.CACHE_NAME))
    try:
        rows = [row[0] for row in con.execute("SELECT body FROM message_fts").fetchall()]
        flag = con.execute("SELECT value FROM meta WHERE key='bodies'").fetchone()
    finally:
        con.close()
    return rows, (flag[0] if flag else None)


def run_main(argv):
    out = io.StringIO()
    code = 0
    with redirect_stdout(out):
        try:
            got = cli.main(list(argv))
            code = 0 if got is None else got
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
    return code, out.getvalue()


def main():
    failures = []

    def check(name, cond):
        if cond:
            print("ok", name)
        else:
            failures.append(name)
            print("FAIL", name)

    check("version is 0.1.9", cli.VERSION == "0.1.9")
    check("messages cache is not the live cache", REAL_HOME not in str(messages_index.db_path("grok-messages")))
    check("chat.db stand-in is not the live library", REAL_HOME not in str(messages_index.CHAT_DB))

    parser = cli.build_parser()
    check("reindex defaults to metadata", parser.parse_args(["reindex"]).index_bodies is False)
    check("onboard defaults to metadata", parser.parse_args(["onboard"]).index_bodies is False)
    check("reindex flag opts into bodies", parser.parse_args(["reindex", "--index-bodies"]).index_bodies is True)

    seen = {}

    def fake_reindex(*args, **kwargs):
        seen["reindex"] = kwargs.get("index_bodies")
        return {"ok": True, "indexes": []}

    def fake_onboard(*args, **kwargs):
        seen["onboard"] = kwargs.get("index_bodies")
        return {"ok": True}

    def fake_guided(*args, **kwargs):
        seen["guided"] = kwargs.get("index_bodies")
        return {"ok": True}, 0

    cli.do_reindex = fake_reindex
    cli.do_onboard = fake_onboard
    cli.do_guided_onboard = fake_guided
    cli.onboard_ping.maybe_ping = lambda: None

    code, _out = run_main(["reindex", "--json"])
    check("reindex passes metadata", code == 0 and seen.get("reindex") is False)
    code, _out = run_main(["reindex", "--index-bodies", "--json"])
    check("reindex passes index-bodies", code == 0 and seen.get("reindex") is True)
    code, _out = run_main(["onboard", "--json"])
    check("onboard passes metadata", code == 0 and seen.get("onboard") is False)
    code, _out = run_main(["onboard", "--guided", "--index-bodies", "--json"])
    check("guided onboard passes index-bodies", code == 0 and seen.get("guided") is True)

    write_source([], with_messages=False)
    meta = messages_index.build(index_bodies=False)
    check("metadata build does not need message.text", meta.get("ok") is True and meta.get("indexBodies") is False and meta.get("mode") == "metadata")
    rows, flag = fts_bodies()
    check("metadata build stores no message text", rows == [] and flag == "0")

    write_source([(1, SECRET)], with_messages=True)
    first = messages_index.build(index_bodies=True)
    rows, flag = fts_bodies()
    check("index-bodies stores the message", first.get("ok") and first.get("indexBodies") is True and rows == [SECRET] and flag == "1")

    write_source([(1, SECRET), (2, SECRET_2)], with_messages=True)
    second = messages_index.build(index_bodies=True)
    rows, flag = fts_bodies()
    check("index-bodies keeps the existing body", second.get("mode") == "incremental" and rows == [SECRET, SECRET_2] and second.get("ftsAdded") == 1)

    cleared = messages_index.build(index_bodies=False)
    rows, flag = fts_bodies()
    blob = messages_index.db_path(messages_index.CACHE_NAME).read_bytes().decode("utf-8", "replace")
    check("metadata build drops stored bodies", cleared.get("mode") == "metadata" and rows == [] and flag == "0" and SECRET not in blob)

    if failures:
        print("failures:", ", ".join(failures))
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
