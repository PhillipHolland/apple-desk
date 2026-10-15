#!/usr/bin/env python3
"""Offline test: onboard.sh replaces a stale ~/bin/grok-desk symlink.

Does not run grok-desk onboard or touch a live home directory.
"""
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from pathlib import Path

LIVE_HOME = os.environ.get("HOME", "")
REPO = Path(__file__).resolve().parents[3]
ONBOARD = REPO / "scripts" / "onboard.sh"
SRC = REPO / "cli" / "grok-desk" / "bin" / "grok-desk"


def main() -> int:
    failures = []

    def check(name, cond):
        if cond:
            print("ok", name)
        else:
            failures.append(name)
            print("FAIL", name)

    check("onboard.sh is executable", ONBOARD.is_file() and os.access(ONBOARD, os.X_OK))
    check("repo grok-desk is executable", SRC.is_file() and os.access(SRC, os.X_OK))
    check("test home is not the live home", True)

    root = Path(tempfile.mkdtemp(prefix="apple-desk-onboard-link-", dir="/tmp"))
    home = root / "home"
    old = root / "old" / "grok-desk"
    old.parent.mkdir(parents=True)
    home.joinpath("bin").mkdir(parents=True)
    home.joinpath(".local/bin").mkdir(parents=True)
    old.write_text("#!/bin/sh\necho stale\n")
    old.chmod(old.stat().st_mode | stat.S_IXUSR)
    dest = home / "bin" / "grok-desk"
    dest.symlink_to(old)
    local = home / ".local" / "bin" / "grok-desk"
    local.symlink_to(old)
    check("stale link starts outside the checkout", dest.resolve() == old.resolve())
    if LIVE_HOME:
        check("fake home is not the live home", LIVE_HOME not in str(home))

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["GROK_DESK_LINKS_ONLY"] = "1"
    env["GROK_DESK_NO_TELEMETRY"] = "1"
    proc = subprocess.run(["bash", str(ONBOARD)], env=env, text=True, capture_output=True)
    check("onboard links-only exits 0", proc.returncode == 0)
    check("did not invoke grok-desk onboard", "Running grok-desk onboard" not in proc.stdout)
    check("relinked grok-desk", "relinked grok-desk" in proc.stdout)
    check("~/bin/grok-desk now points at this checkout", Path(os.readlink(dest)) == SRC)
    check("~/.local/bin/grok-desk now points at this checkout", Path(os.readlink(local)) == SRC)
    check("stale binary was not deleted", old.is_file())

    if failures:
        print(proc.stdout)
        print(proc.stderr)
        print("failures:", ", ".join(failures))
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
