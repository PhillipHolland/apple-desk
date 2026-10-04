#!/usr/bin/env python3
"""Offline checks for grok-calendar alarm. Does not call Calendar.app."""
from __future__ import annotations

import argparse
import importlib.util
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

LIB = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("grok_calendar_cli", LIB / "cli.py")
cli = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cli)

CALLS = []
DRY_RUN_MESSAGE = "dry-run: Calendar.app was not called. Pass --force to apply."
UID = "evt-test-0001"


def fake_call_jxa(payload, timeout, as_json):
    CALLS.append(payload)
    return {
        "ok": True,
        "applied": True,
        "dryRun": False,
        "op": payload.get("op"),
        "uid": payload.get("uid"),
        "minutesBefore": payload.get("minutesBefore"),
        "triggerInterval": -int(payload.get("minutesBefore") or 0),
        "calendar": "Example",
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
    check("alarm exists", subs is not None and "alarm" in subs)
    check("move is not a subcommand", "move" not in subs)
    check("attendees is not a subcommand", "attendees" not in subs)
    check("rsvp is not a subcommand", "rsvp" not in subs)
    check("version is 0.1.6", cli.VERSION == "0.1.6")

    gaps_blob = " ".join(cli.GAPS).lower()
    check("gaps say display alarm dry-run", "display alarm" in gaps_blob and "dry-run" in gaps_blob)
    check("gaps say no calendar property", "no calendar property" in gaps_blob)
    check("gaps refuse eventkit move", "does not use eventkit" in gaps_blob)
    check("gaps omit rsvp names", "rsvp names" in gaps_blob)
    check("gaps do not offer a name dump", "command that prints them" in gaps_blob)

    missing = [
        ["alarm", "--json"],
        ["alarm", "--uid", UID, "--json"],
        ["alarm", "--minutes", "15", "--json"],
        ["alarm", "--uid", UID, "--minutes", "-1", "--json"],
        ["alarm", "--uid", UID, "--minutes", "40321", "--json"],
        ["alarm", "--uid", "   ", "--minutes", "15", "--json"],
        ["alarm", "--uid", UID, "--minutes", "nope", "--json"],
    ]
    for argv in missing:
        label = " ".join(argv)
        code, _out, _err = run(argv)
        check("bad exits 2: " + label, code == 2)
        check("bad does not call Calendar: " + label, CALLS == [])

    code, out, _err = run(["alarm", "--uid", UID, "--minutes", "15", "--json"])
    check("dry-run exit 0", code == 0)
    check("dry-run does not call Calendar", CALLS == [])
    data = json.loads(out)
    check("dry-run ok", data.get("ok") is True and data.get("dryRun") is True and data.get("applied") is False)
    check("dry-run fields", data.get("op") == "alarm" and data.get("uid") == UID and data.get("minutesBefore") == 15)
    check("dry-run message", data.get("message") == DRY_RUN_MESSAGE)
    for banned in ("title", "attendees", "name", "email", "phone", "notes"):
        check("dry-run hides " + banned, banned not in data)

    code, out, _err = run(["alarm", "--uid", UID, "--minutes", "0", "--dry-run", "--force", "--json"])
    check("explicit dry-run beats force", code == 0 and CALLS == [])
    data = json.loads(out)
    check("explicit dry-run zero minutes", data.get("dryRun") is True and data.get("minutesBefore") == 0)

    code, out, _err = run(["alarm", "--uid", UID, "--minutes", "15", "--force", "--json"])
    check("force exit 0", code == 0)
    check("force one call", len(CALLS) == 1)
    sent = CALLS[0]
    check("force payload", sent.get("op") == "alarm" and sent.get("force") is True and sent.get("minutesBefore") == 15 and sent.get("uid") == UID)
    check("force payload has no attendee fields", "attendees" not in sent and "name" not in sent and "email" not in sent)
    data = json.loads(out)
    check("force applied", data.get("applied") is True and data.get("dryRun") is False)
    for banned in ("attendees", "email", "phone", "notes", "title"):
        check("force hides " + banned, banned not in data)

    if failures:
        print("FAILED", len(failures))
        raise SystemExit(1)
    print("all ok")


if __name__ == "__main__":
    main()
