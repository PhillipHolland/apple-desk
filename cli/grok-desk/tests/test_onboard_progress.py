#!/usr/bin/env python3
"""Offline tests for guided onboard progress and --quick.

Uses a temporary HOME. Does not call Apple apps, chat.db, or the network.
"""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

LIVE_HOME = os.environ.get("HOME", "")
ROOT = Path(tempfile.mkdtemp(prefix="grok-desk-onboard-progress-", dir="/tmp"))
FAKE_HOME = ROOT / "home"
FAKE_HOME.mkdir()
os.environ["HOME"] = str(FAKE_HOME)
os.environ["GROK_DESK_NO_TELEMETRY"] = "1"
os.environ["PATH"] = str(ROOT / "empty-path")
(ROOT / "empty-path").mkdir()

LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

import cli  # noqa: E402
import common  # noqa: E402


def ok_doctor(bin_name, timeout, extra_args=None):
    short = bin_name.removeprefix("grok-")
    return {
        "id": short,
        "name": short,
        "bin": bin_name,
        "ok": True,
        "present": True,
        "version": "0.0.0",
        "error": None,
        "exitCode": 0,
        "message": None,
        "settingsPath": None,
        "doctor": {"ok": True, "history": {"available": True}, "automation": "authorized"},
        "automation": "authorized",
        "historyAvailable": True,
    }


def fda_fail(bin_name, timeout, extra_args=None):
    row = ok_doctor(bin_name, timeout, extra_args)
    row.update({
        "ok": False,
        "error": "needs_full_disk_access",
        "exitCode": 5,
        "historyAvailable": False,
        "doctor": {"ok": False, "history": {"available": False}, "automation": "authorized"},
        "message": "Messages history needs Full Disk Access.",
        "settingsPath": cli.SETTINGS_FDA,
    })
    return row


def run_main(argv):
    out = io.StringIO()
    err = io.StringIO()
    code = 0
    with redirect_stdout(out), redirect_stderr(err):
        try:
            got = cli.main(list(argv))
            code = 0 if got is None else got
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

    check("version is 0.1.10", cli.VERSION == "0.1.10")
    check("eleven guided gates", cli.GUIDED_GATE_TOTAL == 11)
    check("fake home is not the live home", LIVE_HOME not in str(FAKE_HOME) if LIVE_HOME else True)

    parser = cli.build_parser()
    check("onboard --quick is off by default", parser.parse_args(["onboard"]).quick is False)
    check("onboard accepts --quick", parser.parse_args(["onboard", "--guided", "--quick"]).quick is True)
    check("reindex accepts --quick", parser.parse_args(["reindex", "--quick"]).quick is True)
    check("quick does not imply guided", parser.parse_args(["onboard", "--quick"]).guided is False)

    called = []

    def fake_surface(name, full, index_contacts, past_days=None, future_days=None, index_bodies=False):
        called.append({
            "name": name,
            "past_days": past_days,
            "future_days": future_days,
            "index_bodies": index_bodies,
        })
        return {"ok": True, "surface": name, "status": "ok"}

    real_surface = cli.reindex_surface
    cli.reindex_surface = fake_surface
    try:
        full = cli.do_reindex(False, None, False)
        check(
            "full reindex walks notes messages calendar reminders",
            [row["name"] for row in called] == ["notes", "messages", "calendar", "reminders"],
        )
        called.clear()
        quick = cli.do_reindex(False, None, False, quick=True)
        names = [row["name"] for row in called]
        check("quick reindex builds messages only", names == ["messages"])
        skipped = [row["surface"] for row in quick["indexes"] if row.get("status") == "skipped_quick"]
        check("quick marks notes calendar reminders skipped", skipped == ["notes", "calendar", "reminders"])
        check("quick reindex is still ok", quick.get("ok") is True and quick.get("quick") is True)
        called.clear()
        only_cal = cli.do_reindex(False, "calendar", False, quick=True)
        check("quick --only calendar still indexes calendar", [row["name"] for row in called] == ["calendar"])
        check(
            "quick --only calendar narrows the window",
            called[0]["past_days"] == cli.QUICK_CALENDAR_PAST_DAYS
            and called[0]["future_days"] == cli.QUICK_CALENDAR_FUTURE_DAYS,
        )
        check("quick --only calendar does not invent skipped rows", only_cal.get("indexes")[0].get("status") != "skipped_quick")
    finally:
        cli.reindex_surface = real_surface

    cli.common.link_if_needed = lambda name: {"name": name, "linked": [], "kept": [], "skipped": True}
    cli.common.which = lambda name: None
    cli.common.read_signature = lambda: "offline-test-signature"
    cli._run_surface_doctor = ok_doctor
    cli.do_reindex = lambda *a, **k: {
        "ok": True,
        "indexes": [{"ok": True, "surface": "messages", "status": "ok"}],
        "quick": bool(k.get("quick")),
    }
    cli.onboard_ping.maybe_ping = lambda: None

    data, code = cli.do_guided_onboard(False, skip_optional=True, skip_signature=True, quick=True, progress=False)
    check("guided quick exits 0", code == 0 and data.get("ok") is True)
    check("guided quick payload marks quick", data.get("quick") is True)
    gate_ids = [g.get("id") for g in data.get("gates") or []]
    check(
        "gate order unchanged",
        gate_ids == [
            "messages-fda",
            "messages-automation",
            "notes",
            "contacts",
            "calendar",
            "reminders",
            "shortcuts",
            "mail",
            "icloud",
            "signature",
            "reindex",
        ],
    )

    err = io.StringIO()
    with redirect_stderr(err):
        data_h, code_h = cli.do_guided_onboard(False, skip_optional=True, skip_signature=True, quick=True, progress=True)
    progress_text = err.getvalue()
    check("human progress exits 0", code_h == 0 and data_h.get("ok") is True)
    check("step 1 on stderr", "[1/11] Full Disk Access (Messages history)" in progress_text)
    check("step 3 calendar-adjacent notes", "[3/11] Automation → Notes" in progress_text)
    check("step 5 calendar", "[5/11] Automation → Calendar" in progress_text)
    check("step 11 reindex", "[11/11] Local reindex" in progress_text)
    check("slow-step hint mentions quick", "--quick" in progress_text or "quick:" in progress_text)
    check("progress stayed off stdout payload", "[1/11]" not in json.dumps(data_h))

    quiet = io.StringIO()
    with redirect_stderr(quiet):
        cli.do_guided_onboard(False, skip_optional=True, skip_signature=True, quick=True, progress=False)
    check("progress=False writes no step lines", "[1/11]" not in quiet.getvalue())

    code, out, err = run_main(["onboard", "--guided", "--skip-signature", "--quick"])
    check("human main prints progress on stderr", code == 0 and "[1/11]" in err and "[11/11]" in err)
    check("human main keeps progress off stdout", "[1/11]" not in out)

    code_j, out_j, err_j = run_main(["onboard", "--guided", "--skip-signature", "--quick", "--json"])
    payload = json.loads(out_j)
    check("json main exits 0", code_j == 0)
    check("json stdout is one object", payload.get("ok") is True and payload.get("mode") == "guided")
    check("json stdout has no progress lines", "[1/11]" not in out_j and "[11/11]" not in out_j)
    check("json mode writes no progress on stderr", "[1/11]" not in err_j)
    check("json payload includes quick", payload.get("quick") is True)

    cli._run_surface_doctor = fda_fail
    fda_data, fda_code = cli.do_guided_onboard(False, skip_optional=True, skip_signature=True, quick=True, progress=False)
    check("FDA fail is still exit 5", fda_code == 5 and fda_data.get("stoppedAt") == "messages-fda")
    check("FDA fail keeps quick in payload", fda_data.get("quick") is True)

    cli._run_surface_doctor = ok_doctor
    cli.common.read_signature = lambda: None
    sig_data, sig_code = cli.do_guided_onboard(False, skip_optional=True, skip_signature=False, quick=True, progress=False)
    check("unset signature is still exit 2", sig_code == 2 and sig_data.get("stoppedAt") == "signature")

    if LIVE_HOME:
        os.environ["HOME"] = LIVE_HOME
    if failures:
        print("failures:", ", ".join(failures))
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
