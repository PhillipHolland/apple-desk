#!/usr/bin/env python3
"""Offline checks for grok-reminders move and flag. Does not call Reminders.app."""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

LIB = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("grok_reminders_cli", LIB / "cli.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

CALLS = []
DRY_RUN_MESSAGE = "dry-run: Reminders.app was not called. Pass --force to apply."


def fake_call_jxa(payload, timeout, as_json):
    CALLS.append(payload)
    return {
        "ok": True,
        "applied": True,
        "dryRun": False,
        "op": payload.get("op"),
        "id": payload.get("id"),
        "state": payload.get("state"),
        "to": payload.get("to"),
        "list": payload.get("to"),
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
    check("flag exists", subs is not None and "flag" in subs)
    check("move exists", "move" in subs)
    check("version is 0.1.5", cli.VERSION == "0.1.5")

    gaps_blob = " ".join(cli.GAPS)
    check("gaps mention recurrence unavailable", "recurrence" in gaps_blob.lower() and "not available" in gaps_blob.lower())
    check("gaps mention EventKit not in build", "EventKit is not in this build" in gaps_blob)
    check("gaps no longer say flag read-only", "Flag is read-only" not in gaps_blob)
    check("gaps no longer say no move", "There is no move between lists" not in gaps_blob)

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
    ]
    for argv in missing:
        label = " ".join(argv)
        code, _out, _err = run(argv)
        check("missing exits 2: " + label, code == 2)
        check("missing does not call Reminders: " + label, CALLS == [])

    dry = [
        (["flag", "--id", "999999", "--state", "flagged", "--json"], "flag", {"state": "flagged"}),
        (["flag", "--id", "999999", "--state", "unflagged", "--json"], "flag", {"state": "unflagged"}),
        (["move", "--id", "999999", "--to", "Example", "--json"], "move", {"to": "Example"}),
    ]
    for argv, op, extra in dry:
        label = " ".join(argv)
        code, out, _err = run(argv)
        check("dry-run exit 0: " + label, code == 0)
        check("dry-run does not call Reminders: " + label, CALLS == [])
        data = json.loads(out)
        check("dry-run ok: " + label, data.get("ok") is True)
        check("dry-run dryRun: " + label, data.get("dryRun") is True)
        check("dry-run applied: " + label, data.get("applied") is False)
        check("dry-run op: " + label, data.get("op") == op)
        check("dry-run id: " + label, data.get("id") == "999999")
        check("dry-run message: " + label, data.get("message") == DRY_RUN_MESSAGE)
        for key, value in extra.items():
            check("dry-run " + key + ": " + label, data.get(key) == value)
        for banned in ("title", "body", "notes", "email", "phone"):
            check("dry-run hides " + banned + ": " + label, banned not in data)

    forced = [
        (["flag", "--id", "999999", "--state", "flagged", "--force", "--json"], "flag", {"state": "flagged"}),
        (["flag", "--id", "999999", "--state", "unflagged", "--force", "--json"], "flag", {"state": "unflagged"}),
        (["move", "--id", "999999", "--to", "Example", "--force", "--json"], "move", {"to": "Example"}),
    ]
    for argv, op, extra in forced:
        label = " ".join(argv)
        code, _out, _err = run(argv)
        check("force exit 0: " + label, code == 0)
        check("force called once: " + label, len(CALLS) == 1)
        payload = CALLS[0] if CALLS else {}
        check("force true: " + label, payload.get("force") is True)
        check("force op: " + label, payload.get("op") == op)
        check("force id: " + label, payload.get("id") == "999999")
        for key, value in extra.items():
            check("force " + key + ": " + label, payload.get(key) == value)

    js = (LIB / "reminders.js").read_text(encoding="utf-8")
    check("jxa force refuse", "payload.force !== true" in js)
    check("jxa sets flagged", "target.flagged =" in js)
    check("jxa move path", 'op === "move"' in js)
    check("jxa no recurrence write", "recurrence" not in js.lower() or "recurrence" not in js)

    readme = (LIB.parent / "README.md").read_text(encoding="utf-8")
    check("readme documents move", "move --id" in readme)
    check("readme documents flag", "flag --id" in readme)
    check("readme documents recurrence gap", "recurrence" in readme.lower() and "EventKit" in readme)
    check("readme dry-run rule", "--force" in readme and "dry-run" in readme.lower())

    if failures:
        print(str(len(failures)) + " failed")
        for name in failures:
            print(" -", name)
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
