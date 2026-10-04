#!/usr/bin/env python3
"""Offline checks for to-note. Stubs Reading List and Notes. Does not write."""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

import cli  # noqa: E402

FAKE_TITLE = "Fixture Article"
FAKE_URL = "https://example.invalid/fixture-article"
FAKE_TITLE_2 = "Other Fixture"
FAKE_URL_2 = "https://example.invalid/other"

READING = [
    {"id": "rl-1", "title": FAKE_TITLE, "url": FAKE_URL, "dateAdded": None},
    {"id": "rl-2", "title": FAKE_TITLE_2, "url": FAKE_URL_2, "dateAdded": None},
    {"id": "rl-3", "title": FAKE_TITLE, "url": "https://example.invalid/dup-title", "dateAdded": None},
]

NOTES_CALLS = []
LOAD_CALLS = []


def fake_load_items(as_json, prefer_cache=True):
    LOAD_CALLS.append({"as_json": as_json, "prefer_cache": prefer_cache})
    meta = {"path": "Library/Safari/Bookmarks.plist", "readable": True, "sizeBytes": 1, "mtime": None}
    return [], list(READING), True, meta


def fake_notes_call(payload, timeout, as_json):
    NOTES_CALLS.append({"payload": payload, "timeout": timeout, "as_json": as_json})
    if payload.get("cmd") != "create-note":
        return {"ok": False, "error": "unexpected_notes_cmd", "message": payload.get("cmd")}
    return {
        "ok": True,
        "created": True,
        "id": "note-fixture-1",
        "title": payload.get("title"),
        "account": "iCloud",
        "folder": payload.get("folder") or "Notes",
        "path": payload.get("folder") or "Notes",
    }


class FakeNotes:
    def call_jxa(self, payload, timeout, as_json):
        return fake_notes_call(payload, timeout, as_json)


def run(argv):
    NOTES_CALLS.clear()
    LOAD_CALLS.clear()
    cli.load_items = fake_load_items
    cli._NOTES = FakeNotes()
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

    check("version is 0.1.2", cli.VERSION == "0.1.2")
    subs = None
    import argparse
    for action in cli.build_parser()._actions:
        if isinstance(action, argparse._SubParsersAction):
            subs = action.choices
            break
    check("to-note exists", subs is not None and "to-note" in subs)

    gaps = " ".join(cli.GAPS).lower()
    check("gaps name to-note", "to-note" in gaps)
    check("gaps say dry-run default", "dry-run" in gaps)
    check("gaps say create-note bridge", "create-note" in gaps)
    check("gaps say reading list not edited", "not added" in gaps or "not edit" in gaps)

    missing = [
        ["to-note", "--json"],
        ["to-note", "--index", "1", "--url", FAKE_URL, "--json"],
        ["to-note", "--index", "1", "--title", FAKE_TITLE, "--json"],
        ["to-note", "--url", FAKE_URL, "--title", FAKE_TITLE, "--json"],
        ["to-note", "--index", "0", "--json"],
    ]
    for argv in missing:
        label = " ".join(argv)
        code, _out, _err = run(argv)
        check("invalid exits 2: " + label, code == 2)
        check("invalid does not call Notes: " + label, NOTES_CALLS == [])
        # index 0 fails before load; others with dual selectors also before load
        if "--index" in argv and "0" in argv:
            check("bad index 0 skips load: " + label, LOAD_CALLS == [])
        elif argv == ["to-note", "--json"]:
            check("missing target skips load: " + label, LOAD_CALLS == [])
        elif selectors_count(argv) > 1:
            check("dual selector skips load: " + label, LOAD_CALLS == [])

    code, out, _err = run(["to-note", "--index", "1", "--json"])
    data = json.loads(out)
    check("dry-run exit 0", code == 0)
    check("dry-run ok", data.get("ok") is True and data.get("dryRun") is True and data.get("applied") is False)
    check("dry-run title", data.get("title") == FAKE_TITLE)
    check("dry-run url", data.get("url") == FAKE_URL)
    check("dry-run note body is url", (data.get("note") or {}).get("body") == FAKE_URL)
    check("dry-run note title", (data.get("note") or {}).get("title") == FAKE_TITLE)
    check("dry-run bridge", data.get("bridge") == "grok-notes-create-note")
    check("dry-run did not call Notes", NOTES_CALLS == [])
    check("dry-run loaded reading list", len(LOAD_CALLS) == 1)
    check("dry-run no bookmark write", data.get("modifiesBookmarks") is False)
    check("dry-run no url open", data.get("opensUrls") is False)

    code, out, _err = run(["to-note", "--url", FAKE_URL_2, "--json"])
    data = json.loads(out)
    check("url dry-run exit 0", code == 0 and data.get("title") == FAKE_TITLE_2)
    check("url dry-run still no Notes", NOTES_CALLS == [])

    code, out, _err = run(["to-note", "--title", FAKE_TITLE_2, "--folder", "Reading", "--json"])
    data = json.loads(out)
    check("title dry-run folder echoed", code == 0 and data.get("folder") == "Reading")
    check("title dry-run note folder", (data.get("note") or {}).get("folder") == "Reading")
    check("title dry-run no Notes", NOTES_CALLS == [])

    code, _out, _err = run(["to-note", "--title", FAKE_TITLE, "--json"])
    check("ambiguous title exits 2", code == 2)
    check("ambiguous did not call Notes", NOTES_CALLS == [])

    code, _out, _err = run(["to-note", "--index", "9", "--json"])
    check("bad index exits 2", code == 2)
    check("bad index did not call Notes", NOTES_CALLS == [])

    code, _out, _err = run(["to-note", "--url", "https://example.invalid/missing", "--json"])
    check("missing url exits 1", code == 1)
    check("missing url did not call Notes", NOTES_CALLS == [])

    code, out, _err = run(["to-note", "--index", "1", "--force", "--json"])
    data = json.loads(out)
    check("force exit 0", code == 0 and data.get("applied") is True and data.get("dryRun") is False)
    check("force notes once", len(NOTES_CALLS) == 1)
    payload = (NOTES_CALLS[0] or {}).get("payload") or {}
    check("force uses create-note", payload.get("cmd") == "create-note")
    check("force title", payload.get("title") == FAKE_TITLE)
    check("force body is url", payload.get("body") == FAKE_URL)
    check("force note id", data.get("noteId") == "note-fixture-1")
    check("force still no bookmark write", data.get("modifiesBookmarks") is False)
    check("force still no url open", data.get("opensUrls") is False)

    code, out, _err = run(["to-note", "--url", FAKE_URL_2, "--folder", "Reading", "--force", "--json"])
    payload = (NOTES_CALLS[0] or {}).get("payload") or {}
    check("force with folder exit 0", code == 0)
    check("force with folder field", payload.get("folder") == "Reading")
    check("force with folder create-note", payload.get("cmd") == "create-note" and payload.get("title") == FAKE_TITLE_2)

    # text dry-run output
    code, out, _err = run(["to-note", "--index", "2"])
    check("text dry-run exit 0", code == 0)
    check("text dry-run prints title", FAKE_TITLE_2 in out)
    check("text dry-run prints url", FAKE_URL_2 in out)
    check("text dry-run says dry-run", "dry-run" in out.lower())
    check("text dry-run no Notes", NOTES_CALLS == [])

    readme = (LIB.parent / "README.md").read_text(encoding="utf-8")
    doc = (LIB.parents[2] / "docs" / "SAFARI_READING_LIST_NOTE.md").read_text(encoding="utf-8")
    focus = (LIB.parents[2] / "docs" / "FOCUS_AND_SAFARI.md").read_text(encoding="utf-8")
    blob = readme + "\n" + doc + "\n" + focus
    check("readme names command", "to-note" in readme)
    check("doc says dry-run default", "dry-run" in doc.lower() and "--force" in doc)
    check("doc says create-note", "create-note" in doc)
    check("focus names to-note", "to-note" in focus)
    for banned in ("phillip", "holland", "@gmail", "mini-3", "555-"):
        check("docs hide " + banned, banned not in blob.lower())

    if failures:
        print(str(len(failures)) + " failed")
        for name in failures:
            print(" -", name)
        return 1
    print("all ok")
    return 0


def selectors_count(argv):
    n = 0
    if "--index" in argv:
        n += 1
    if "--url" in argv:
        n += 1
    if "--title" in argv:
        n += 1
    return n


if __name__ == "__main__":
    sys.exit(main())
