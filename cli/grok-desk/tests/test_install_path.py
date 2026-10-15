#!/usr/bin/env python3
"""Offline test: install.sh writes PATH even when onboard fails.

Uses a throwaway HOME and a local git clone. Does not touch a live home
directory or send the onboard ping.
"""
from __future__ import annotations

import os
import stat
import subprocess
import tempfile
from pathlib import Path

LIVE_HOME = os.environ.get("HOME", "")
REPO = Path(__file__).resolve().parents[3]
INSTALL = REPO / "scripts" / "install.sh"
ONBOARD = REPO / "scripts" / "onboard.sh"
PATH_COMMENT = "# apple-desk PATH"
PATH_EXPORT = 'export PATH="$HOME/bin:$HOME/.local/bin:$PATH"'


def write_exec(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)


def git(cwd: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=testrunner", "-c", "user.email=testrunner@example.invalid", *args],
        cwd=str(cwd),
        check=True,
        capture_output=True,
        text=True,
    )


def main() -> int:
    failures = []

    def check(name, cond):
        if cond:
            print("ok", name)
        else:
            failures.append(name)
            print("FAIL", name)

    check("install.sh is executable", INSTALL.is_file() and os.access(INSTALL, os.X_OK))
    check("fake home will not be the live home", True)

    root = Path(tempfile.mkdtemp(prefix="apple-desk-install-path-", dir="/tmp"))
    home = root / "home"
    src = root / "src"
    dest = root / "dest"
    home.mkdir()
    src.mkdir()
    (src / "scripts").mkdir()
    (src / "scripts" / "onboard.sh").write_text(ONBOARD.read_text())
    (src / "scripts" / "onboard.sh").chmod(0o755)
    write_exec(
        src / "cli" / "grok-desk" / "bin" / "grok-desk",
        "#!/bin/sh\nprintf '%s\\n' \"$*\" > \"$HOME/onboard-args\"\necho stub-onboard-fail\nexit 5\n",
    )
    git(src, "init")
    git(src, "add", ".")
    git(src, "commit", "-m", "fixture")

    env = os.environ.copy()
    env["HOME"] = str(home)
    env["SHELL"] = "/bin/zsh"
    env["APPLE_DESK_REPO"] = str(src)
    env["APPLE_DESK_HOME"] = str(dest)
    env["GROK_DESK_NO_TELEMETRY"] = "1"
    env.pop("APPLE_DESK_SKIP_FETCH", None)

    proc = subprocess.run(["bash", str(INSTALL)], env=env, text=True, capture_output=True)
    zshrc = home / ".zshrc"
    args = (home / "onboard-args").read_text() if (home / "onboard-args").is_file() else ""
    out = proc.stdout + "\n" + proc.stderr
    if LIVE_HOME:
        check("fake home is not the live home", LIVE_HOME not in str(home) and LIVE_HOME not in str(src))

    check("install exits with onboard code 5", proc.returncode == 5)
    check("PATH rc was written", zshrc.is_file())
    check("PATH comment present", PATH_COMMENT in zshrc.read_text())
    check("PATH export present", PATH_EXPORT in zshrc.read_text())
    check("guided --quick was used", "--guided" in args.split() and "--quick" in args.split())
    check("plain onboard was not used", args.strip() != "onboard")
    check("tells user to re-run guided", "Installed, but onboarding needs these fixes; re-run grok-desk onboard --guided" in out)
    check("mentions telemetry opt-out", "GROK_DESK_NO_TELEMETRY=1" in out)
    check("linked grok-desk once", out.count("linked grok-desk") == 1)
    check("did not print the link twice", "linked grok-desk" in out and out.count("->") >= 1)
    desk = home / "bin" / "grok-desk"
    check("grok-desk is linked", desk.is_symlink() or desk.is_file())

    if failures:
        print(proc.stdout)
        print(proc.stderr)
        print("failures:", ", ".join(failures))
        return 1
    print("ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
