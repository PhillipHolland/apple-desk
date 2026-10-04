#!/usr/bin/env python3
"""Existing-chat send returns from a chat.db receipt. No Messages process and no real send."""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

os.environ["GROK_MESSAGES_CONFIRM_DIR"] = tempfile.mkdtemp(prefix="grok-messages-existing-confirm-")

import cli  # noqa: E402
import db  # noqa: E402

GUID = "any;-;fixture@example.invalid"
OTHER = "any;-;other@example.invalid"
BODY = "fixture body that must not be sent"
CHAT_ID = 7


def make_db(path: Path, older_text: str = "older fixture") -> None:
    con = sqlite3.connect(path)
    con.executescript(
        """
        create table chat (ROWID integer primary key, guid text);
        create table message (
            ROWID integer primary key,
            text text,
            is_from_me integer,
            error integer,
            is_sent integer,
            associated_message_type integer
        );
        create table chat_message_join (chat_id integer, message_id integer);
        """
    )
    con.execute("insert into chat (ROWID, guid) values (?, ?)", (CHAT_ID, GUID))
    con.execute("insert into chat (ROWID, guid) values (8, ?)", (OTHER,))
    con.execute(
        """
        insert into message (ROWID, text, is_from_me, error, is_sent, associated_message_type)
        values (10, ?, 1, 0, 1, 0)
        """,
        (older_text,),
    )
    con.execute("insert into chat_message_join (chat_id, message_id) values (?, 10)", (CHAT_ID,))
    con.commit()
    con.close()


def insert_outgoing(path: Path, rowid: int, chat_id: int, text: str, error: int = 0, assoc: int = 0) -> None:
    con = sqlite3.connect(path)
    con.execute(
        """
        insert into message (ROWID, text, is_from_me, error, is_sent, associated_message_type)
        values (?, ?, 1, ?, ?, ?)
        """,
        (rowid, text, error, 1 if error == 0 else 0, assoc),
    )
    con.execute(
        "insert into chat_message_join (chat_id, message_id) values (?, ?)",
        (chat_id, rowid),
    )
    con.commit()
    con.close()


class Runner:
    def __init__(self, path: Path, insert=None, code: int = 0):
        self.path = path
        self.insert = insert
        self.code = code
        self.calls = []

    def run(self, script, argv, timeout):
        self.calls.append({"script": script, "argv": list(argv), "timeout": timeout})
        if self.insert:
            insert_outgoing(self.path, **self.insert)
        return type("Proc", (), {"returncode": self.code, "stdout": "dispatched\n", "stderr": ""})()


def chat():
    return {"guid": GUID, "rowid": CHAT_ID, "style": "direct", "identifier": "fixture@example.invalid"}


def main():
    failures = []

    def check(name, cond):
        if cond:
            print("ok", name)
        else:
            failures.append(name)
            print("FAIL", name)

    script = cli.EXISTING_CHAT_SEND_SCRIPT
    check("script does not wait for the reply", "ignoring application responses" in script)
    check("script sends to the chat id", "send theMessage to chat id chatId" in script)
    check("script does not walk chats or participants", "participants" not in script and "every chat" not in script and "repeat" not in script)
    check("script does not touch the UI", "activate" not in script and "System Events" not in script)
    check("event bound is under the old 45s wait", cli.SEND_EVENT_TIMEOUT < 45)
    check("message body is not baked into the script", BODY not in script)

    root = Path(tempfile.mkdtemp(prefix="grok-messages-existing-db-"))
    path = root / "chat.db"
    make_db(path, older_text=BODY)
    db.DB_PATH = path
    cli.RECEIPT_WAIT_SECONDS = 0.2
    runner = Runner(path)
    cli._run_osascript = runner.run
    result = cli.call_existing_send(chat(), BODY, False)
    check("an older copy of the text is not a receipt", result.get("ok") is False and result.get("error") == "send_unconfirmed" and result.get("sent") is False)
    check("unconfirmed send is not repeated", len(runner.calls) == 1)
    check("send argv is the guid and the text", runner.calls[0]["argv"] == [GUID, BODY] and runner.calls[0]["script"] == script)
    check("send timeout is the short bound", runner.calls[0]["timeout"] == cli.SEND_EVENT_TIMEOUT)

    path = root / "accepted.db"
    make_db(path)
    db.DB_PATH = path
    runner = Runner(path, insert={"rowid": 11, "chat_id": CHAT_ID, "text": BODY, "error": 0}, code=-14)
    cli._run_osascript = runner.run
    result = cli.call_existing_send(chat(), BODY, False)
    check(
        "a stuck reply still counts once chat.db has the text",
        result.get("ok") is True and result.get("sent") is True and result.get("confirmedBy") == "chat.db" and result.get("messageRowId") == 11,
    )
    check("stuck reply was still one send", len(runner.calls) == 1)

    path = root / "failed.db"
    make_db(path)
    db.DB_PATH = path
    runner = Runner(path, insert={"rowid": 11, "chat_id": CHAT_ID, "text": BODY, "error": 22})
    cli._run_osascript = runner.run
    result = cli.call_existing_send(chat(), BODY, False)
    check("a failed row is not success and is not resent", result.get("ok") is False and result.get("sent") is False and "22" in result.get("message", "") and len(runner.calls) == 1)

    path = root / "other.db"
    make_db(path)
    db.DB_PATH = path
    runner = Runner(path, insert={"rowid": 11, "chat_id": 8, "text": BODY, "error": 0})
    cli._run_osascript = runner.run
    result = cli.call_existing_send(chat(), BODY, False)
    check("a row in another chat is not this send", result.get("error") == "send_unconfirmed" and len(runner.calls) == 1)

    path = root / "reaction.db"
    make_db(path)
    db.DB_PATH = path
    runner = Runner(path, insert={"rowid": 11, "chat_id": CHAT_ID, "text": BODY, "error": 0, "assoc": 2000})
    cli._run_osascript = runner.run
    result = cli.call_existing_send(chat(), BODY, False)
    check("a reaction row is not a send receipt", result.get("error") == "send_unconfirmed" and len(runner.calls) == 1)

    # The command path must keep using the receipt function for an existing chat.
    # This stub raises if the waiting JXA send is selected.
    os.environ["GROK_MESSAGES_CONFIRM_DIR"] = str(root / "confirm")
    cli.ALLOWLIST = root / "allowlist-absent"

    def open_db(_as_json):
        con = sqlite3.connect(":memory:")
        con.row_factory = sqlite3.Row
        con.executescript(
            """
            create table chat (
                ROWID integer primary key, guid text, chat_identifier text,
                display_name text, service_name text, style integer, is_filtered integer
            );
            create table handle (ROWID integer primary key, id text);
            create table chat_handle_join (chat_id integer, handle_id integer);
            create table chat_message_join (chat_id integer, message_id integer, message_date integer);
            insert into chat values (7, 'any;-;kept@fixture.invalid', 'kept@fixture.invalid', null, 'iMessage', 45, 0);
            insert into handle values (7, 'kept@fixture.invalid');
            insert into chat_handle_join values (7, 7);
            """
        )
        return con

    seen = {}

    def call_existing_send(target, text, as_json):
        seen["guid"] = target.get("guid")
        seen["text"] = text
        return {"ok": True, "sent": True, "confirmedBy": "chat.db", "group": False}

    def call_send_jxa(payload, timeout, as_json):
        raise AssertionError("waiting send was used for an existing chat")

    cli.open_db = open_db
    cli.call_existing_send = call_existing_send
    cli.call_send_jxa = call_send_jxa
    import io
    from contextlib import redirect_stderr, redirect_stdout
    out = io.StringIO()
    err = io.StringIO()
    code = 0
    with redirect_stdout(out), redirect_stderr(err):
        try:
            cli.main(["send", "--to", "kept@fixture.invalid", "--text", BODY, "--json"])
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
    token = json.loads(out.getvalue()).get("confirmToken")
    out = io.StringIO()
    err = io.StringIO()
    code = 0
    with redirect_stdout(out), redirect_stderr(err):
        try:
            cli.main(["send", "--to", "kept@fixture.invalid", "--text", BODY, "--force", "--confirm", token, "--json"])
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
    data = json.loads(out.getvalue())
    check("force on an existing chat uses the receipt send", code == 0 and data.get("sent") is True and seen.get("guid") == "any;-;kept@fixture.invalid" and seen.get("text") == BODY)

    if failures:
        print(f"{len(failures)} failed")
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
