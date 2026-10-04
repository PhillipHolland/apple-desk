#!/usr/bin/env python3
"""Offline dry-run checks. No Reminders.app, no reminder-cli, no EventKit."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

os.environ["HOME"] = tempfile.mkdtemp(prefix="grok-reminders-dry-", dir="/tmp")
LIB = Path(__file__).resolve().parent
sys.path.insert(0, str(LIB))

import cli  # noqa: E402
import pim_wrap  # noqa: E402

FAKE_BIN = "/tmp/grok-pim-wrap-test-bin-not-real"


def run_cli(argv):
    calls = []

    def jxa(payload, timeout, as_json):
        calls.append(payload)
        return {"ok": True, "id": payload.get("id") or "rem-fixture", "title": payload.get("title"), "list": "Reminders"}

    def no_proc(*args, **kwargs):
        raise AssertionError("subprocess was called")

    cli.call_jxa = jxa
    cli.subprocess.run = no_proc
    out = io.StringIO()
    err = io.StringIO()
    code = 0
    with redirect_stdout(out), redirect_stderr(err):
        try:
            cli.main(list(argv))
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
    return code, out.getvalue(), calls


def run_wrap(argv):
    calls = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        raise AssertionError("reminder-cli was called")

    old_run = pim_wrap.subprocess.run
    old_bin = pim_wrap.binary
    old_argv = sys.argv
    pim_wrap.subprocess.run = fake_run
    pim_wrap.binary = lambda: FAKE_BIN
    sys.argv = ["pim_wrap.py", *argv]
    code = 0
    try:
        try:
            pim_wrap.main()
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
    finally:
        pim_wrap.subprocess.run = old_run
        pim_wrap.binary = old_bin
        sys.argv = old_argv
    return code, calls


def main():
    failures = []

    def check(name, cond):
        if cond:
            print("ok", name)
        else:
            failures.append(name)
            print("FAIL", name)

    source = Path(pim_wrap.__file__).read_text(encoding="utf-8")
    check("wrap does not import EventKit", "import EventKit" not in source and "EKReminder" not in source)
    check("version is 0.1.6", cli.VERSION == "0.1.6")

    code, out, calls = run_cli(["add", "--title", "Call office", "--json"])
    check("add defaults to dry-run", code == 0 and json.loads(out).get("dryRun") is True and calls == [])

    code, out, calls = run_cli(["add", "--title", "Call office", "--force", "--dry-run", "--json"])
    check("add dry-run wins over force", code == 0 and json.loads(out).get("applied") is False and calls == [])

    code, out, calls = run_cli(["done", "--id", "rem-fixture", "--json"])
    check("done defaults to dry-run", code == 0 and json.loads(out).get("dryRun") is True and calls == [])

    code, out, calls = run_cli(["add", "--title", "Call office", "--force", "--json"])
    check("add force reaches JXA", code == 0 and calls and calls[0].get("op") == "add" and calls[0].get("force") is True)

    code, out, calls = run_cli(["delete", "--id", "rem-fixture", "--json"])
    check("delete stays on force", code == 2 and json.loads(out).get("error") == "needs_force" and calls == [])

    code, out, calls = run_cli(["delete", "--id", "rem-fixture", "--dry-run", "--force", "--json"])
    check("delete dry-run does not apply", code == 0 and json.loads(out).get("dryRun") is True and calls == [])

    code, calls = run_wrap(["add", "--title", "Call office", "--dry-run"])
    check("wrap add dry-run does not call reminder-cli", code == 86 and calls == [])

    code, calls = run_wrap(["add", "--title", "Call office"])
    check("wrap add without force falls through", code == 86 and calls == [])

    code, calls = run_wrap(["done", "--id", "rem-fixture", "--dry-run", "--force"])
    check("wrap done dry-run falls through", code == 86 and calls == [])

    code, calls = run_wrap(["done", "--id", "rem-fixture"])
    check("wrap done without force falls through", code == 86 and calls == [])

    code, calls = run_wrap(["delete", "--id", "rem-fixture", "--dry-run"])
    check("wrap delete dry-run does not call reminder-cli", code == 86 and calls == [])

    code, calls = run_wrap(["delete", "--id", "rem-fixture"])
    check("wrap delete without force does not call reminder-cli", code == 2 and calls == [])

    if failures:
        print("failures:", ", ".join(failures))
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
