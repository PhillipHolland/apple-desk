#!/usr/bin/env python3
"""Offline checks for promote-checklist. Stubs Notes and Reminders. Does not write."""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

import cli  # noqa: E402

NOTE_ID = "note-1"
NOTE_TITLE = "Packing list"
HTML = "<ul><li>Pack bag</li><li>Pack bag</li><li>Lock door</li></ul>"
NOTE = {
    "id": NOTE_ID,
    "title": NOTE_TITLE,
    "html": HTML,
    "locked": False,
    "body": "Pack bag",
}

NOTES_CALLS = []
REM_CALLS = []
WRITE_CMDS = {"edit", "checklist-add", "create-note", "import-md", "delete-note", "move", "append"}


def fake_notes(payload, timeout, as_json):
    NOTES_CALLS.append(payload)
    if payload.get("cmd") != "show":
        return {"ok": False, "error": "unexpected_notes_cmd", "message": payload.get("cmd")}
    return {"ok": True, "matches": 1, "notes": [dict(NOTE)]}


def fake_reminders(payload, timeout, as_json):
    REM_CALLS.append(payload)
    return {
        "ok": True,
        "added": True,
        "id": "reminder-1",
        "title": payload.get("title"),
        "list": payload.get("list") or "Reminders",
        "due": payload.get("due"),
    }


def run(argv):
    NOTES_CALLS.clear()
    REM_CALLS.clear()
    cli.call_jxa = fake_notes
    reminders = cli.load_reminders_cli()
    reminders.call_jxa = fake_reminders
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

    check("version is 0.2.4", cli.VERSION == "0.2.4")
    subs = None
    import argparse
    for action in cli.build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            subs = action.choices
            break
    check("promote-checklist exists", subs is not None and "promote-checklist" in subs)

    gaps = " ".join(cli.GAPS).lower()
    check("gaps say line is not marked done", "does not mark the line done" in gaps)
    check("gaps say checked is not reliable", "not reliable" in gaps)
    check("gaps say backlink is plain text", "plain text" in gaps and "link-a-note" in gaps)

    missing = [
        ["promote-checklist", "--json"],
        ["promote-checklist", "--index", "1", "--json"],
        ["promote-checklist", "--id", NOTE_ID, "--json"],
        ["promote-checklist", "--id", NOTE_ID, "--index", "1", "--text", "Pack bag", "--json"],
        ["promote-checklist", "--id", NOTE_ID, "--index", "1", "--due", "tomorrow", "--json"],
        ["promote-checklist", "--id", NOTE_ID, "--text", "   ", "--json"],
    ]
    for argv in missing:
        label = " ".join(argv)
        code, _out, _err = run(argv)
        check("invalid exits 2: " + label, code == 2)
        check("invalid does not call Notes: " + label, NOTES_CALLS == [])
        check("invalid does not call Reminders: " + label, REM_CALLS == [])

    code, out, _err = run(["promote-checklist", "--id", NOTE_ID, "--index", "3", "--json"])
    data = json.loads(out)
    check("dry-run exit 0", code == 0)
    check("dry-run ok", data.get("ok") is True and data.get("dryRun") is True and data.get("applied") is False)
    check("dry-run line", data.get("line") == "Lock door" and data.get("index") == 3)
    check("dry-run title is the line", (data.get("reminder") or {}).get("title") == "Lock door")
    notes = (data.get("reminder") or {}).get("notes") or ""
    check("dry-run backlink id", NOTE_ID in notes)
    check("dry-run backlink title", NOTE_TITLE in notes)
    check("dry-run omits due", "due" not in (data.get("reminder") or {}))
    check("dry-run checklist unchanged", data.get("checklistChanged") is False)
    check("dry-run read show only", NOTES_CALLS == [{"cmd": "show", "id": NOTE_ID, "full": True}])
    check("dry-run did not call Reminders", REM_CALLS == [])
    check("dry-run no write cmd", all(c.get("cmd") not in WRITE_CMDS for c in NOTES_CALLS))

    code, out, _err = run(["promote-checklist", "--id", NOTE_ID, "--text", "Lock door", "--due", "2026-10-04", "--list", "Reminders", "--json"])
    data = json.loads(out)
    check("text dry-run exit 0", code == 0)
    check("text dry-run due echoed", data.get("due") == "2026-10-04" and data.get("list") == "Reminders")
    check("text dry-run plan due", (data.get("reminder") or {}).get("due") == "2026-10-04")
    check("text dry-run still no Reminders write", REM_CALLS == [])
    check("text dry-run show only", len(NOTES_CALLS) == 1 and NOTES_CALLS[0].get("cmd") == "show")

    code, _out, _err = run(["promote-checklist", "--id", NOTE_ID, "--text", "Pack bag", "--json"])
    check("ambiguous text exits 2", code == 2)
    check("ambiguous did not call Reminders", REM_CALLS == [])
    check("ambiguous show only", len(NOTES_CALLS) == 1 and NOTES_CALLS[0].get("cmd") == "show")

    code, _out, _err = run(["promote-checklist", "--id", NOTE_ID, "--index", "9", "--json"])
    check("bad index exits 2", code == 2)
    check("bad index did not call Reminders", REM_CALLS == [])

    code, out, _err = run(["promote-checklist", "--id", NOTE_ID, "--index", "3", "--force", "--json"])
    data = json.loads(out)
    check("force exit 0", code == 0 and data.get("applied") is True and data.get("dryRun") is False)
    check("force notes show only", NOTES_CALLS == [{"cmd": "show", "id": NOTE_ID, "full": True}])
    check("force reminders once", len(REM_CALLS) == 1)
    payload = REM_CALLS[0] if REM_CALLS else {}
    check("force uses add op", payload.get("op") == "add" and payload.get("force") is True)
    check("force title", payload.get("title") == "Lock door")
    check("force notes contain backlink", NOTE_ID in (payload.get("notes") or "") and NOTE_TITLE in (payload.get("notes") or ""))
    check("force omits due when not passed", "due" not in payload)
    check("force omits list when not passed", "list" not in payload)
    check("force checklist unchanged", data.get("checklistChanged") is False)
    check("force reminder id", data.get("reminderId") == "reminder-1")

    code, _out, _err = run([
        "promote-checklist", "--id", NOTE_ID, "--text", "Lock door",
        "--due", "2026-10-04 15:30", "--list", "Reminders", "--force", "--json",
    ])
    payload = REM_CALLS[0] if REM_CALLS else {}
    check("force with due exit 0", code == 0)
    check("force with due field", payload.get("due") == "2026-10-04 15:30" and payload.get("list") == "Reminders")
    check("force with due still add", payload.get("op") == "add" and payload.get("title") == "Lock door")

    readme = (LIB.parent / "README.md").read_text(encoding="utf-8")
    doc = (LIB.parents[2] / "docs" / "NOTES_CHECKLIST_REMINDER.md").read_text(encoding="utf-8")
    blob = readme + "\n" + doc
    check("readme names command", "promote-checklist" in readme)
    check("doc says not marked done", "not mark the line done" in doc or "not marked done" in blob)
    check("doc says dry-run default", "dry-run" in doc.lower() and "--force" in doc)
    for banned in ("phillip", "holland", "@", "mini"):
        check("docs hide " + banned, banned not in blob.lower())

    if failures:
        print(str(len(failures)) + " failed")
        for name in failures:
            print(" -", name)
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    sys.exit(main())
