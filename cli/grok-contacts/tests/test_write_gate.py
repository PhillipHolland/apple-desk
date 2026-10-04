#!/usr/bin/env python3
"""Offline contacts write gate. No Contacts.app."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

os.environ["HOME"] = tempfile.mkdtemp(prefix="grok-contacts-gate-", dir="/tmp")
LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

import cli  # noqa: E402


def run(argv):
    calls = []

    def jxa(payload, timeout, as_json):
        calls.append(payload)
        return {"ok": True, "id": payload.get("id") or "contact-1"}

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


def main():
    failures = []

    def check(name, cond):
        if cond:
            print("ok", name)
        else:
            failures.append(name)
            print("FAIL", name)

    check("version is 0.1.4", cli.VERSION == "0.1.4")

    code, out, calls = run(["create", "--first", "Ada", "--last", "Lovelace", "--json"])
    check("create defaults to dry-run", code == 0 and json.loads(out).get("dryRun") is True and calls == [])

    code, out, calls = run(["update", "--id", "contact-1", "--org", "Analytical Engines", "--json"])
    check("update defaults to dry-run", code == 0 and json.loads(out).get("dryRun") is True and calls == [])

    code, out, calls = run(["create", "--first", "Ada", "--dry-run", "--force", "--json"])
    check("create dry-run wins", code == 0 and json.loads(out).get("applied") is False and calls == [])

    code, out, calls = run(["create", "--first", "Ada", "--force", "--json"])
    check("create force reaches JXA", code == 0 and calls and calls[0].get("op") == "create" and calls[0].get("force") is True)

    code, out, calls = run(["delete", "--id", "contact-1", "--json"])
    check("delete stays on force", code == 2 and json.loads(out).get("error") == "needs_force" and calls == [])

    if failures:
        print("failures:", ", ".join(failures))
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
