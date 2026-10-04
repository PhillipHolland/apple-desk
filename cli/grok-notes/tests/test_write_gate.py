#!/usr/bin/env python3
"""Offline notes write gate and metadata reindex. No Notes.app and no live cache."""
from __future__ import annotations

import io
import json
import os
import sqlite3
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

REAL_HOME = os.environ.get("HOME", "")
os.environ["HOME"] = tempfile.mkdtemp(prefix="grok-notes-gate-", dir="/tmp")

LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

import cli  # noqa: E402
import index as indexlib  # noqa: E402

SECRET = "secret-note-body"
NOTE = {
    "id": "note-1",
    "title": "Fixture title",
    "modified": "2026-01-02T00:00:00Z",
    "created": "2026-01-01T00:00:00Z",
    "folderId": "folder-1",
    "folder": "Notes",
    "account": "iCloud",
    "body": SECRET,
    "snippet": SECRET,
}
FOLDER = {
    "id": "folder-1",
    "name": "Notes",
    "account": "iCloud",
    "parent": "",
    "path": "Notes",
    "depth": 0,
    "shared": False,
    "trash": False,
}


def run_cli(argv):
    calls = []

    def jxa(payload, timeout, as_json):
        calls.append(payload)
        # notes.js refuses delete before Notes.app when force is not true.
        if payload.get("cmd") == "delete-note" and payload.get("force") is not True:
            return {"ok": False, "error": "needs_force", "message": "delete-note requires --force"}
        return {"ok": True, "id": "note-1", "title": payload.get("title")}

    def no_proc(*args, **kwargs):
        raise AssertionError("subprocess was called")

    cli.call_jxa = jxa
    cli.subprocess.run = no_proc
    out = io.StringIO()
    err = io.StringIO()
    code = 0
    with redirect_stdout(out), redirect_stderr(err):
        try:
            got = cli.main(list(argv))
            code = 0 if got is None else got
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
    return code, out.getvalue(), calls


def bodies_in_index():
    con = sqlite3.connect(indexlib.DB_PATH)
    try:
        row = con.execute("SELECT body FROM notes WHERE id='note-1'").fetchone()
        flag = con.execute("SELECT value FROM meta WHERE key='bodies'").fetchone()
    finally:
        con.close()
    return (row[0] if row else None), (flag[0] if flag else None)


def main():
    failures = []

    def check(name, cond):
        if cond:
            print("ok", name)
        else:
            failures.append(name)
            print("FAIL", name)

    check("index path is not the live cache", REAL_HOME not in str(indexlib.DB_PATH))
    check("version is 0.2.4", cli.VERSION == "0.2.4")

    code, out, calls = run_cli(["create-note", "--title", "Fixture title", "--body", SECRET, "--json"])
    data = json.loads(out)
    check("create-note defaults to dry-run", code == 0 and data.get("dryRun") is True and calls == [] and SECRET not in out)

    code, out, calls = run_cli(["edit", "--id", "note-1", "--body", SECRET, "--json"])
    check("edit defaults to dry-run", code == 0 and json.loads(out).get("dryRun") is True and calls == [])

    code, out, calls = run_cli(["append", "--id", "note-1", "--text", SECRET, "--json"])
    check("append defaults to dry-run", code == 0 and json.loads(out).get("dryRun") is True and calls == [])

    code, out, calls = run_cli(["create-note", "--title", "Fixture title", "--body", SECRET, "--dry-run", "--force", "--json"])
    check("create-note dry-run wins", code == 0 and json.loads(out).get("applied") is False and calls == [])

    code, out, calls = run_cli(["create-note", "--title", "Fixture title", "--force", "--json"])
    check("create-note force reaches JXA", code == 0 and calls and calls[0].get("cmd") == "create-note" and calls[0].get("force") is True)

    code, out, calls = run_cli(["delete-note", "--id", "note-1", "--json"])
    check(
        "delete stays on force",
        code != 0
        and calls
        and calls[0].get("cmd") == "delete-note"
        and calls[0].get("force") is False
        and json.loads(out).get("error") == "needs_force",
    )
    code, out, calls = run_cli(["delete-note", "--id", "note-1", "--force", "--json"])
    check("delete force reaches JXA", code == 0 and calls and calls[0].get("force") is True)

    calls = []

    def jxa(payload, timeout=120):
        calls.append(dict(payload))
        mode = payload.get("mode")
        if mode == "stamp":
            return {"ok": True, "notes": [dict(NOTE)], "folders": [dict(FOLDER)], "warnings": []}
        if mode in {"full", "bodies"}:
            return {"ok": True, "notes": [dict(NOTE)], "folders": [dict(FOLDER)], "warnings": []}
        if payload.get("cmd") == "folders":
            return {"ok": True, "folders": [dict(FOLDER)]}
        return {"ok": False, "error": "unexpected", "message": str(payload)}

    meta = indexlib.reindex(jxa, index_bodies=False)
    body, flag = bodies_in_index()
    check("default reindex is metadata", meta.get("ok") and meta.get("indexBodies") is False and meta.get("mode") == "metadata")
    check("default reindex does not store the body", body == "" and flag == "0" and SECRET not in indexlib.DB_PATH.read_bytes().decode("utf-8", "replace"))
    check("default reindex does not ask for bodies", all(item.get("mode") == "stamp" for item in calls))

    calls.clear()
    kept = indexlib.reindex(jxa, index_bodies=True)
    body, flag = bodies_in_index()
    check("index-bodies stores the body", kept.get("indexBodies") is True and body == SECRET and flag == "1")

    calls.clear()
    again = indexlib.reindex(jxa, index_bodies=True)
    body, flag = bodies_in_index()
    modes = [item.get("mode") for item in calls]
    check("index-bodies keeps the stored body", again.get("ok") and body == SECRET and "full" not in modes and "bodies" not in modes)

    if failures:
        print("failures:", ", ".join(failures))
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
