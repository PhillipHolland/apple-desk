#!/usr/bin/env python3
"""Offline checks for grok-mail flag, move, and mark-read. Does not call Mail."""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

LIB = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("grok_mail_cli", LIB / "cli.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

CALLS = []
DRY_RUN_MESSAGE = "dry-run: Mail.app was not called. Pass --force to apply."


def fake_call_jxa(payload, timeout, as_json):
    CALLS.append(payload)
    return {
        "ok": True,
        "applied": True,
        "sent": False,
        "dryRun": False,
        "op": payload.get("op"),
        "id": payload.get("id"),
        "state": payload.get("state"),
        "to": payload.get("to"),
    }


cli.call_jxa = fake_call_jxa


def run(argv):
    CALLS.clear()
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

    subs = None
    for action in cli.build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            subs = action.choices
            break
    check("send is not a subcommand", subs is not None and "send" not in subs)
    check("flag exists", "flag" in subs)
    check("move exists", "move" in subs)
    check("mark-read exists", "mark-read" in subs)

    code, _out, _err = run(["send"])
    check("send argv exit 2", code == 2)
    check("send argv does not call Mail", CALLS == [])

    missing = [
        ["flag", "--json"],
        ["flag", "--state", "flagged", "--json"],
        ["flag", "--id", "999999", "--json"],
        ["flag", "--id", "999999", "--state", "nope", "--json"],
        ["flag", "--force", "--json"],
        ["move", "--json"],
        ["move", "--id", "999999", "--json"],
        ["move", "--to", "Example", "--json"],
        ["move", "--id", "999999", "--to", "   ", "--json"],
        ["move", "--force", "--to", "Example", "--json"],
        ["mark-read", "--json"],
        ["mark-read", "--force", "--json"],
    ]
    for argv in missing:
        label = " ".join(argv)
        code, _out, _err = run(argv)
        check("missing exits 2: " + label, code == 2)
        check("missing does not call Mail: " + label, CALLS == [])

    dry = [
        (["flag", "--id", "999999", "--state", "flagged", "--json"], "flag", {"state": "flagged"}),
        (["flag", "--id", "999999", "--state", "unflagged", "--json"], "flag", {"state": "unflagged"}),
        (["move", "--id", "999999", "--to", "Example", "--json"], "move", {"to": "Example"}),
        (["mark-read", "--id", "999999", "--json"], "mark-read", {}),
        (["mark-read", "--id", "999999", "--mailbox", "INBOX", "--account", "<account>"], "mark-read", {}),
    ]
    for argv, op, extra in dry:
        label = " ".join(argv)
        code, out, _err = run(argv)
        check("dry-run exit 0: " + label, code == 0)
        check("dry-run does not call Mail: " + label, CALLS == [])
        if "--json" not in argv:
            continue
        data = json.loads(out)
        check("dry-run ok: " + label, data.get("ok") is True)
        check("dry-run dryRun: " + label, data.get("dryRun") is True)
        check("dry-run applied: " + label, data.get("applied") is False)
        check("dry-run sent: " + label, data.get("sent") is False)
        check("dry-run op: " + label, data.get("op") == op)
        check("dry-run id: " + label, data.get("id") == 999999)
        check("dry-run message: " + label, data.get("message") == DRY_RUN_MESSAGE)
        for key, value in extra.items():
            check("dry-run " + key + ": " + label, data.get(key) == value)
        for banned in ("subject", "sender", "body", "address", "addresses"):
            check("dry-run hides " + banned + ": " + label, banned not in data)

    forced = [
        (["flag", "--id", "999999", "--state", "flagged", "--force", "--json"], "flag", {"state": "flagged"}),
        (["move", "--id", "999999", "--to", "Example", "--mailbox", "INBOX", "--force", "--json"], "move", {"to": "Example", "mailbox": "INBOX"}),
        (["mark-read", "--id", "42", "--account", "<account>", "--force", "--json"], "mark-read", {"account": "<account>"}),
    ]
    for argv, op, extra in forced:
        label = " ".join(argv)
        code, _out, _err = run(argv)
        check("force exit 0: " + label, code == 0)
        check("force called once: " + label, len(CALLS) == 1)
        payload = CALLS[0] if CALLS else {}
        check("force true: " + label, payload.get("force") is True)
        check("force op: " + label, payload.get("op") == op)
        check("force has no send key: " + label, "send" not in payload)
        for key, value in extra.items():
            check("force " + key + ": " + label, payload.get(key) == value)

    js = (LIB / "mail.js").read_text(encoding="utf-8")
    check("jxa send reject", 'payload.op === "send" || payload.send' in js)
    check("jxa force refuse", "payload.force !== true" in js)
    check("jxa sets flaggedStatus", "msg.flaggedStatus = state === \"flagged\"" in js)
    check("jxa sets readStatus", "msg.readStatus = true" in js)
    check("jxa moves to mailbox", "app.move(msg, { to: dest.mailbox })" in js)

    if failures:
        print(str(len(failures)) + " failed")
        for name in failures:
            print(" -", name)
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
