#!/usr/bin/env python3
"""Offline argv and redaction checks for the imsg history and watch wraps.

No live imsg process. Fake argv and fake JSON only.
"""
from __future__ import annotations

import io
import json
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

import cli  # noqa: E402

CHAT = {
    "rowid": 7,
    "guid": "fixture-chat",
    "name": "Fixture",
    "identifier": "fixture",
    "service": "iMessage",
    "style": "direct",
}
BODY = "secret-body"
REPLY = "secret-reply"
PATH = "/tmp/fixture-attachment/photo.jpg"
FAKE_LINE = json.dumps({
    "id": 1,
    "chat_id": 7,
    "sender": "fixture",
    "is_from_me": False,
    "text": BODY,
    "reply_to_text": REPLY,
    "created_at": "2026-01-01T00:00:00Z",
    "is_reaction": False,
    "attachments": [{
        "transfer_name": "photo.jpg",
        "filename": PATH,
        "mime_type": "image/jpeg",
        "total_bytes": 12,
        "is_sticker": False,
        "original_path": PATH,
        "converted_path": "/tmp/fixture-attachment/photo-cached.jpg",
        "missing": False,
    }],
})
FORBIDDEN = ("send", "react", "tapback", "launch", "convert-attachments", "bb-events")


def run(argv):
    out = io.StringIO()
    err = io.StringIO()
    code = 0
    with redirect_stdout(out), redirect_stderr(err):
        try:
            cli.main(list(argv))
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
    return code, out.getvalue(), err.getvalue()


def install_stubs(calls):
    class _Con:
        def close(self):
            return None

    def open_db(_as_json):
        return _Con()

    def resolve(_con, _target, _service, _as_json):
        return dict(CHAT)

    def imsg_path():
        return "/tmp/fixture-imsg"

    def run_readonly(argv):
        calls.append(("run", list(argv)))
        return 0, FAKE_LINE + "\n", ""

    class FakeProc:
        def __init__(self, lines):
            self.stdout = iter(lines)
            self.stderr = io.StringIO("")
            self.returncode = 0
            self.closed = False

        def poll(self):
            return 0 if self.closed else None

        def wait(self, timeout=None):
            self.closed = True
            return 0

        def terminate(self):
            self.closed = True

        def kill(self):
            self.closed = True

    def stream(argv):
        calls.append(("stream", list(argv)))
        return FakeProc([FAKE_LINE + "\n"])

    cli.open_db = open_db
    cli._resolve = resolve
    cli._imsg_path = imsg_path
    cli._run_imsg_readonly = run_readonly
    cli._stream_imsg = stream


def main():
    failures = []

    def check(name, cond):
        if cond:
            print("ok", name)
        else:
            failures.append(name)
            print("FAIL", name)

    check("version is 0.2.13", cli.VERSION == "0.2.13")
    check("gaps name the read wrap", "imsg history and imsg watch" in " ".join(cli.GAPS))

    calls = []
    install_stubs(calls)
    code, out, err = run(["history", "--chat-guid", "fixture-chat", "--json"])
    check("history dry-run exits 0", code == 0 and err == "")
    payload = json.loads(out)
    command = payload["command"]
    check("history dry-run not executed", payload["executed"] is False and payload["dryRun"] is True)
    check("history argv is history json", " history " in f" {command} " and "--json" in command and "--chat-id 7" in command)
    check("history dry-run did not call imsg", calls == [])
    check("history argv has no write subcommand", all(flag not in command for flag in FORBIDDEN))
    check("history dry-run hides body and path", BODY not in out and PATH not in out and REPLY not in out)

    calls.clear()
    code, out, err = run(["history", "--chat-guid", "fixture-chat", "--force", "--json"])
    check("history force exits 0", code == 0)
    payload = json.loads(out)
    blob = json.dumps(payload)
    check("history force ran once", calls and calls[0][0] == "run" and len(calls) == 1)
    check("history force argv matches", calls[0][1][1:] == ["history", "--chat-id", "7", "--limit", "15", "--json"])
    check("history force hides body", BODY not in blob and REPLY not in blob and payload["bodies"] is False)
    check("history force hides path", PATH not in blob and "original_path" not in blob)
    check("history force keeps metadata", payload["messages"][0]["textLength"] == len(BODY))
    check("history force keeps attachment name", payload["messages"][0]["attachments"][0]["name"] == "photo.jpg")

    calls.clear()
    code, out, err = run(["history", "--chat-guid", "fixture-chat", "--force", "--reveal-path", "--json"])
    payload = json.loads(out)
    check("reveal path is explicit", payload["messages"][0]["attachments"][0]["path"] == PATH)
    check("reveal still hides body", BODY not in out and REPLY not in out)
    check("reveal warns", "private file" in payload.get("warning", ""))
    check("reveal does not include converted cache path", "photo-cached" not in out)

    calls.clear()
    code, out, err = run(["watch", "--to", "fixture", "--json"])
    payload = json.loads(out)
    check("watch dry-run does not start", payload["executed"] is False and calls == [])
    check("watch argv is watch json", payload["command"].split()[-4:] == ["watch", "--chat-id", "7", "--json"] or payload["command"].endswith("watch --chat-id 7 --json"))
    parts = payload["command"].split()
    check("watch subcommand is watch", "watch" in parts and "history" not in parts[1:])
    check("watch argv has no write subcommand", all(flag not in payload["command"] for flag in FORBIDDEN))
    check("watch dry-run hides body and path", BODY not in out and PATH not in out)

    calls.clear()
    code, out, err = run(["watch", "--chat-guid", "fixture-chat", "--force", "--json"])
    payload = json.loads(out)
    check("watch force used the stream stub", calls and calls[0][0] == "stream")
    check("watch force argv", calls[0][1][1:] == ["watch", "--chat-id", "7", "--json"])
    blob = json.dumps(payload)
    check("watch force hides body and path", BODY not in blob and PATH not in blob and REPLY not in blob)
    check("watch force closed", True)

    code, out, err = run(["history", "--help"])
    check("history help is dry-run text", code == 0 and "does not run imsg" in out)
    code, out, err = run(["watch", "--help"])
    check("watch help is opt-in", code == 0 and "does not start" in out.lower() or "does not start imsg" in out)

    if failures:
        print("failures", ", ".join(failures))
        raise SystemExit(1)
    print("all ok")


if __name__ == "__main__":
    main()
