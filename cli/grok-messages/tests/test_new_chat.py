#!/usr/bin/env python3
"""Offline checks for missing 1:1 creation. No Messages process and no real handle."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

# Confirm tokens must not land in the real home. Set this before importing cli.
os.environ["GROK_MESSAGES_CONFIRM_DIR"] = tempfile.mkdtemp(prefix="grok-messages-confirm-test-")

import cli  # noqa: E402
import db  # noqa: E402

HANDLE = "fixture@example.invalid"
PHONE = "+15555550100"
KEPT = "kept@fixture.invalid"
MEMBER = "member@fixture.invalid"
GROUP_NAME = "Fixture Group"
BODY = "fixture body"


def memory_db(rows):
    con = sqlite3.connect(":memory:")
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        create table chat (
            ROWID integer primary key,
            guid text,
            chat_identifier text,
            display_name text,
            service_name text,
            style integer,
            is_filtered integer
        );
        create table handle (
            ROWID integer primary key,
            id text
        );
        create table chat_handle_join (
            chat_id integer,
            handle_id integer
        );
        create table chat_message_join (
            chat_id integer,
            message_id integer,
            message_date integer
        );
        """
    )
    for row in rows:
        con.execute(
            """
            insert into chat (
                ROWID, guid, chat_identifier, display_name, service_name, style, is_filtered
            ) values (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["rowid"],
                row["guid"],
                row["identifier"],
                row.get("name"),
                row.get("service") or "iMessage",
                row["style"],
                0,
            ),
        )
        con.execute("insert into handle (ROWID, id) values (?, ?)", (row["rowid"], row["handle"]))
        con.execute(
            "insert into chat_handle_join (chat_id, handle_id) values (?, ?)",
            (row["rowid"], row["rowid"]),
        )
    return con


EMPTY = []
KEPT_CHAT = {
    "rowid": 1,
    "guid": "iMessage;-;kept",
    "identifier": KEPT,
    "name": None,
    "handle": KEPT,
    "style": 45,
}
GROUP_CHAT = {
    "rowid": 2,
    "guid": "iMessage;+;chatfixture",
    "identifier": "chatfixture",
    "name": GROUP_NAME,
    "handle": MEMBER,
    "style": 43,
}


class Guard:
    def __init__(self):
        self.jxa = []
        self.send = []
        self.opened = 0

    def install(self, rows):
        guard = self

        def open_db(_as_json):
            guard.opened += 1
            return memory_db(rows)

        def call_jxa(payload, timeout, as_json):
            guard.jxa.append(payload)
            if payload.get("op") == "resolve_participant":
                return {"ok": True, "found": True, "handle": payload.get("handle"), "service": "iMessage"}
            if payload.get("op") == "resolve_chat":
                return {"ok": True, "found": True, "group": False, "participantCount": 1}
            raise AssertionError("unexpected resolve " + json.dumps(payload))

        def call_send_jxa(payload, timeout, as_json):
            guard.send.append(payload)
            if payload.get("createIfMissing"):
                return {
                    "ok": True,
                    "sent": True,
                    "created": True,
                    "route": "new_participant",
                    "handle": payload.get("handle"),
                }
            return {
                "ok": True,
                "sent": True,
                "route": "participant",
                "handle": payload.get("handle"),
                "group": False,
            }

        cli.open_db = open_db
        cli.call_jxa = call_jxa
        cli.call_send_jxa = call_send_jxa
        cli.ALLOWLIST = Path(tempfile.gettempdir()) / "grok-messages-allowlist-absent-fixture"


def run(argv, rows):
    guard = Guard()
    guard.install(rows)
    out = io.StringIO()
    err = io.StringIO()
    code = 0
    with redirect_stdout(out), redirect_stderr(err):
        try:
            cli.main(list(argv))
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
    return code, out.getvalue(), err.getvalue(), guard


def main():
    failures = []

    def check(name, cond):
        if cond:
            print("ok", name)
        else:
            failures.append(name)
            print("FAIL", name)

    check("version is 0.2.13", cli.VERSION == "0.2.13")
    check("email handle", db.is_new_chat_handle(HANDLE))
    check("phone handle", db.is_new_chat_handle(PHONE))
    check("display name is not a handle", not db.is_new_chat_handle(GROUP_NAME))
    check("guid is not a handle", not db.is_new_chat_handle("iMessage;+;chatfixture"))
    check("short digits are not a handle", not db.is_new_chat_handle("555"))

    code, out, err, guard = run(["send", "--to", HANDLE, "--json"], EMPTY)
    check("missing text refuses", code == 2 and json.loads(out)["error"] == "missing_text" and guard.send == [] and guard.jxa == [])

    code, out, err, guard = run(["send", "--text", BODY, "--json"], EMPTY)
    check("missing target refuses", code == 2 and json.loads(out)["error"] == "missing_target" and guard.opened == 0)

    code, out, err, guard = run(["send", "--to", HANDLE, "--text", "   ", "--json"], EMPTY)
    check("blank body refuses", code == 2 and json.loads(out)["error"] == "missing_text" and guard.send == [])

    code, out, err, guard = run(["send", "--to", GROUP_NAME, "--text", BODY, "--dry-run", "--json"], EMPTY)
    check("name does not create", code == 2 and json.loads(out)["error"] == "not_found" and guard.send == [] and guard.jxa == [])

    code, out, err, guard = run(["send", "--to", HANDLE, "--text", BODY, "--json"], EMPTY)
    data = json.loads(out)
    check("default is a dry-run", code == 0 and data.get("dryRun") is True and data.get("sent") is False and guard.send == [] and guard.jxa == [])
    check("default prints a confirm token", bool(data.get("confirmToken")) and BODY not in out)

    code, out, err, guard = run(["send", "--to", HANDLE, "--text", BODY, "--dry-run", "--json"], EMPTY)
    data = json.loads(out)
    check("dry-run exits 0", code == 0 and err == "")
    check("dry-run would create", data.get("wouldCreate") is True and data.get("created") is False)
    check("dry-run did not send", data.get("sent") is False and data.get("dryRun") is True)
    check("dry-run names first message", data.get("createMeans") == "first_message" and data.get("route") == "new_participant")
    check("dry-run did not call Messages", guard.jxa == [] and guard.send == [])
    check("dry-run keeps the handle", data.get("handle") == HANDLE)

    code, out, err, guard = run(["send", "--to", PHONE, "--text", BODY, "--dry-run", "--force", "--json"], EMPTY)
    data = json.loads(out)
    check("dry-run wins over force", code == 0 and data.get("sent") is False and guard.send == [] and guard.jxa == [] and bool(data.get("confirmToken")))

    code, out, err, guard = run(["send", "--to", HANDLE, "--text", BODY, "--force", "--json"], EMPTY)
    check("force alone does not send", code == 2 and json.loads(out)["error"] == "needs_confirm" and guard.opened == 0 and guard.send == [])

    code, out, err, guard = run(["send", "--to", HANDLE, "--text", BODY, "--json"], EMPTY)
    token = json.loads(out)["confirmToken"]
    code, out, err, guard = run(["send", "--to", HANDLE, "--text", BODY, "--force", "--confirm", token, "--json"], EMPTY)
    data = json.loads(out)
    check("force exits 0", code == 0 and err == "")
    check("force sent once", data.get("sent") is True and data.get("created") is True and len(guard.send) == 1)
    payload = guard.send[0]
    check(
        "force uses the same send op",
        payload.get("op") == "send_participant" and payload.get("createIfMissing") is True and "directChatId" not in payload,
    )
    check("force did not resolve first", guard.jxa == [])
    check("force text is the body", payload.get("text") == BODY and payload.get("handle") == HANDLE)

    code, out, err, guard = run(["send", "--to", KEPT, "--text", BODY, "--dry-run", "--json"], [KEPT_CHAT])
    data = json.loads(out)
    check("existing chat is not a create", code == 0 and data.get("wouldCreate") is False and data.get("route") == "participant")
    check("existing dry-run does not send", guard.send == [] and data.get("sent") is False)
    check("existing dry-run does not call Messages", guard.jxa == [])

    code, out, err, guard = run(["send", "--to", KEPT, "--text", BODY, "--json"], [KEPT_CHAT])
    token = json.loads(out)["confirmToken"]
    code, out, err, guard = run(["send", "--to", KEPT, "--text", BODY, "--force", "--confirm", token, "--json"], [KEPT_CHAT])
    data = json.loads(out)
    payload = guard.send[0] if guard.send else {}
    check("existing force reuses the chat", code == 0 and data.get("sent") is True and "createIfMissing" not in payload)
    check("existing force keeps the guid", payload.get("directChatId") == KEPT_CHAT["guid"] and payload.get("op") == "send_participant")

    code, out, err, guard = run(["send", "--to", GROUP_NAME, "--text", BODY, "--dry-run", "--json"], [GROUP_CHAT])
    check("group name stays refused", code == 2 and json.loads(out)["error"] == "refusing_group" and guard.send == [] and guard.jxa == [])

    code, out, err, guard = run(["send", "--to", MEMBER, "--text", BODY, "--dry-run", "--json"], [GROUP_CHAT])
    data = json.loads(out) if out else {}
    check("handle in a group can start a 1:1", code == 0 and data.get("wouldCreate") is True and data.get("route") == "new_participant")
    check("group guid is not the send target", guard.send == [] and "chatfixture" not in out)

    listed = Path(tempfile.gettempdir()) / "grok-messages-allowlist-fixture"
    listed.write_text("# fixture only\n" + HANDLE + "\n", encoding="utf-8")
    try:
        code, out, err, guard = run(["send", "--to", PHONE, "--text", BODY, "--dry-run", "--json"], EMPTY)
        # run() resets ALLOWLIST to the absent path. Re-run with the file set after install.
        guard = Guard()
        guard.install(EMPTY)
        cli.ALLOWLIST = listed
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        code = 0
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            try:
                cli.main(["send", "--to", PHONE, "--text", BODY, "--dry-run", "--json"])
            except SystemExit as exc:
                code = exc.code if exc.code is not None else 0
        check("allowlist blocks an unlisted handle", code == 2 and json.loads(out_buf.getvalue())["error"] == "allowlist_blocked" and guard.send == [])

        code = 0
        out_buf = io.StringIO()
        err_buf = io.StringIO()
        with redirect_stdout(out_buf), redirect_stderr(err_buf):
            try:
                cli.main(["send", "--to", HANDLE, "--text", BODY, "--dry-run", "--json"])
            except SystemExit as exc:
                code = exc.code if exc.code is not None else 0
        data = json.loads(out_buf.getvalue())
        check("allowlist permits the listed handle", code == 0 and data.get("wouldCreate") is True and guard.send == [])
    finally:
        listed.unlink(missing_ok=True)

    if failures:
        print(f"{len(failures)} failed")
        raise SystemExit(1)
    print("all ok")


if __name__ == "__main__":
    main()
