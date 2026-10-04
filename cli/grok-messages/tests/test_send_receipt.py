#!/usr/bin/env python3
"""Offline receipt and unstick-once checks. No Messages process and no real send."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
import uuid
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

ROOT = Path(tempfile.mkdtemp(prefix="grok-messages-receipt-", dir="/tmp"))
os.environ["HOME"] = str(ROOT / "home")
os.environ["GROK_MESSAGES_CONFIRM_DIR"] = str(ROOT / "confirm")
os.environ["GROK_MESSAGES_RECEIPT_WAIT"] = "0"
(ROOT / "home").mkdir()

LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

import cli  # noqa: E402

HANDLE = "kept@fixture.invalid"
BODY = "fixture body"
GUID = "iMessage;-;kept"


class Proc:
    def __init__(self, code=0, stdout="", stderr=""):
        self.returncode = code
        self.stdout = stdout
        self.stderr = stderr


def shared_db():
    name = "gm" + uuid.uuid4().hex
    uri = f"file:{name}?mode=memory&cache=shared"
    con = sqlite3.connect(uri, uri=True)
    con.executescript(
        """
        create table chat (
            ROWID integer primary key, guid text, chat_identifier text,
            display_name text, service_name text, style integer, is_filtered integer
        );
        create table handle (ROWID integer primary key, id text);
        create table chat_handle_join (chat_id integer, handle_id integer);
        create table chat_message_join (chat_id integer, message_id integer, message_date integer);
        create table message (
            ROWID integer primary key, text text, is_from_me integer, is_read integer
        );
        """
    )
    con.execute(
        "insert into chat (ROWID, guid, chat_identifier, display_name, service_name, style, is_filtered) values (1, ?, ?, null, 'iMessage', 45, 0)",
        (GUID, HANDLE),
    )
    con.execute("insert into handle (ROWID, id) values (1, ?)", (HANDLE,))
    con.execute("insert into chat_handle_join (chat_id, handle_id) values (1, 1)")
    con.commit()
    return uri, con


def insert_outgoing(uri, text):
    con = sqlite3.connect(uri, uri=True)
    cur = con.execute(
        "insert into message (text, is_from_me, is_read) values (?, 1, 1)",
        (text,),
    )
    con.execute(
        "insert into chat_message_join (chat_id, message_id, message_date) values (1, ?, 1)",
        (cur.lastrowid,),
    )
    con.commit()
    con.close()


class Guard:
    def __init__(self, scripts):
        self.scripts = list(scripts)
        self.payloads = []
        self.relaunches = []
        self.procs = []
        self.uri, self.keep = shared_db()

    def install(self):
        guard = self

        def open_db(_as_json):
            con = sqlite3.connect(guard.uri, uri=True)
            con.row_factory = sqlite3.Row
            return con

        def run_jxa(payload, timeout):
            guard.payloads.append(payload)
            if not guard.scripts:
                raise AssertionError("run_jxa called more than the script allows")
            step = guard.scripts.pop(0)
            if step == "timeout":
                return Proc(142, "", "Alarm clock")
            if step == "ok":
                return Proc(0, json.dumps({
                    "ok": True,
                    "sent": True,
                    "route": "participant",
                    "handle": payload.get("handle"),
                    "group": False,
                }))
            if step == "ok-receipt":
                insert_outgoing(guard.uri, payload.get("text"))
                return Proc(0, json.dumps({
                    "ok": True,
                    "sent": True,
                    "route": "participant",
                    "handle": payload.get("handle"),
                    "group": False,
                }))
            raise AssertionError("unknown step " + str(step))

        def relaunch_messages():
            guard.relaunches.append(True)

        def no_proc(*args, **kwargs):
            guard.procs.append(args)
            raise AssertionError("subprocess was called")

        cli.open_db = open_db
        cli.run_jxa = run_jxa
        cli.relaunch_messages = relaunch_messages
        cli.subprocess.run = no_proc
        cli.ALLOWLIST = ROOT / "allowlist-absent"


def run(argv, scripts):
    guard = Guard(scripts)
    guard.install()
    out = io.StringIO()
    err = io.StringIO()
    code = 0
    with redirect_stdout(out), redirect_stderr(err):
        try:
            cli.main(list(argv))
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
    return code, out.getvalue(), err.getvalue(), guard


def token_for(guard_scripts=()):
    code, out, err, guard = run(["send", "--to", HANDLE, "--text", BODY, "--json"], guard_scripts)
    data = json.loads(out)
    return data["confirmToken"], code, guard


def main():
    failures = []

    def check(name, cond):
        if cond:
            print("ok", name)
        else:
            failures.append(name)
            print("FAIL", name)

    token, code, guard = token_for()
    check("dry-run does not script Messages", code == 0 and guard.payloads == [] and guard.relaunches == [] and guard.procs == [])

    code, out, err, guard = run(
        ["send", "--to", HANDLE, "--text", BODY, "--force", "--confirm", token, "--json"],
        ["ok-receipt"],
    )
    data = json.loads(out)
    check("receipt counts as sent", code == 0 and data.get("sent") is True and data.get("receipt") == "chat.db")
    check("receipt send did not relaunch", guard.relaunches == [] and len(guard.payloads) == 1)
    check("receipt send did not call subprocess", guard.procs == [])
    check("receipt payload is participant", guard.payloads[0].get("op") == "send_participant")

    token, _, _ = token_for()
    code, out, err, guard = run(
        ["send", "--to", HANDLE, "--text", BODY, "--force", "--confirm", token, "--json"],
        ["ok"],
    )
    data = json.loads(out)
    check("missing receipt is send_unconfirmed", code != 0 and data.get("error") == "send_unconfirmed" and data.get("sent") is False)
    check("missing receipt does not relaunch", guard.relaunches == [] and len(guard.payloads) == 1)

    token, _, _ = token_for()
    code, out, err, guard = run(
        ["send", "--to", HANDLE, "--text", BODY, "--force", "--confirm", token, "--json"],
        ["timeout", "ok-receipt"],
    )
    data = json.loads(out)
    check("timeout without flag does not retry", code == 4 and json.loads(out)["error"] == "automation_timeout")
    check("timeout without flag does not relaunch", guard.relaunches == [] and len(guard.payloads) == 1 and guard.scripts == ["ok-receipt"])

    token, _, _ = token_for()
    code, out, err, guard = run(
        ["send", "--to", HANDLE, "--text", BODY, "--force", "--confirm", token, "--unstick-once", "--json"],
        ["timeout", "ok-receipt"],
    )
    data = json.loads(out)
    check("unstick-once retries once and sends", code == 0 and data.get("sent") is True and data.get("receipt") == "chat.db")
    check("unstick-once relaunches once", len(guard.relaunches) == 1 and len(guard.payloads) == 2 and guard.procs == [])
    check("unstick retry uses the same op", guard.payloads[0] == guard.payloads[1])

    token, _, _ = token_for()
    code, out, err, guard = run(
        ["send", "--to", HANDLE, "--text", BODY, "--force", "--confirm", token, "--unstick-once", "--json"],
        ["timeout", "timeout", "ok-receipt"],
    )
    check("second timeout stops", code == 4 and json.loads(out)["error"] == "automation_timeout")
    check("second timeout relaunched only once", len(guard.relaunches) == 1 and len(guard.payloads) == 2 and guard.scripts == ["ok-receipt"])

    token, _, guard = token_for()
    code, out, err, guard = run(
        ["send", "--to", HANDLE, "--text", BODY, "--dry-run", "--unstick-once", "--force", "--json"],
        ["timeout"],
    )
    check("dry-run ignores unstick-once", code == 0 and guard.payloads == [] and guard.relaunches == [] and json.loads(out).get("sent") is False)

    if failures:
        print("failures:", ", ".join(failures))
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
