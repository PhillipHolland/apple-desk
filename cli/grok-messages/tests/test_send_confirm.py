#!/usr/bin/env python3
"""Offline confirm-token checks. No Messages process and no real send."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import stat
import sys
import tempfile
import time
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REAL_HOME = os.environ.get("HOME", "")
ROOT = Path(tempfile.mkdtemp(prefix="grok-messages-confirm-", dir="/tmp"))
os.environ["HOME"] = str(ROOT / "home")
os.environ["GROK_MESSAGES_CONFIRM_DIR"] = str(ROOT / "confirm")
(ROOT / "home").mkdir()

LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

import cli  # noqa: E402

HANDLE = "fixture@example.invalid"
BODY = "fixture body text"
OTHER = "other fixture body"


def memory_db():
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
        """
    )
    return con


class Guard:
    def install(self):
        guard = self
        self.jxa = []
        self.send = []
        self.procs = []

        def open_db(_as_json):
            return memory_db()

        def call_jxa(payload, timeout, as_json):
            guard.jxa.append(payload)
            return {"ok": True, "found": False}

        def call_send_jxa(payload, timeout, as_json):
            guard.send.append(payload)
            raise AssertionError("send was invoked")

        def no_proc(*args, **kwargs):
            guard.procs.append(args)
            raise AssertionError("subprocess was called")

        cli.open_db = open_db
        cli.call_jxa = call_jxa
        cli.call_send_jxa = call_send_jxa
        cli.subprocess.run = no_proc
        cli.ALLOWLIST = ROOT / "allowlist-absent"


def run(argv):
    guard = Guard()
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


def main():
    failures = []

    def check(name, cond):
        if cond:
            print("ok", name)
        else:
            failures.append(name)
            print("FAIL", name)

    code, out, err, guard = run(["send", "--to", HANDLE, "--text", BODY, "--json"])
    data = json.loads(out)
    token = data.get("confirmToken") or ""
    path = cli.confirm_file()
    raw = path.read_text(encoding="utf-8") if path.is_file() else ""
    stored = json.loads(raw) if raw else {}
    mode = stat.S_IMODE(path.stat().st_mode) if path.is_file() else 0
    dir_mode = stat.S_IMODE(path.parent.stat().st_mode) if path.is_file() else 0

    check("default does not send", code == 0 and data.get("dryRun") is True and data.get("sent") is False)
    check("default does not open Messages", guard.send == [] and guard.jxa == [] and guard.procs == [])
    check("token is outside the real home", REAL_HOME not in str(path) and str(path).startswith(str(ROOT)))
    check("token file is mode 0600", mode == 0o600)
    check("token dir is mode 0700", dir_mode == 0o700)
    check("token file has no message body", BODY not in raw and "text" not in stored and stored.get("text_sha256"))
    check("token file binds the recipient", stored.get("recipient", "").startswith("to:" + HANDLE))
    check("token expires in 10 minutes", int(stored.get("expires") or 0) - int(time.time()) <= 600)

    code, out, err, guard = run(["send", "--to", HANDLE, "--text", BODY, "--force", "--confirm", "x", "--json"])
    check("short token mismatches", code == 2 and json.loads(out)["error"] == "confirm_mismatch" and guard.send == [])

    code, out, err, guard = run(["send", "--to", HANDLE, "--text", OTHER, "--force", "--confirm", token, "--json"])
    check("text mismatch does not send", code == 2 and json.loads(out)["error"] == "confirm_mismatch" and guard.send == [])
    check("mismatch keeps the token", path.is_file() and BODY not in path.read_text(encoding="utf-8"))

    code, out, err, guard = run(["send", "--to", "other@example.invalid", "--text", BODY, "--force", "--confirm", token, "--json"])
    check("recipient mismatch does not send", code == 2 and json.loads(out)["error"] == "confirm_mismatch" and guard.send == [])

    stored = json.loads(path.read_text(encoding="utf-8"))
    stored["expires"] = int(time.time()) - 5
    path.write_text(json.dumps(stored) + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    code, out, err, guard = run(["send", "--to", HANDLE, "--text", BODY, "--force", "--confirm", token, "--json"])
    check("expired token does not send", code == 2 and json.loads(out)["error"] == "confirm_expired" and guard.send == [])

    if failures:
        print("failures:", ", ".join(failures))
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
