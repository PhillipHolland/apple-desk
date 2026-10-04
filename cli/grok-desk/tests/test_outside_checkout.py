#!/usr/bin/env python3
"""Offline doctor hint for grok-* executables that resolve outside this checkout.

Fake PATH entries live under /tmp. This does not read the live home directory,
relink binaries, copy files, or run the executables.
"""
from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

LIVE_HOME = os.environ.get("HOME", "")
ROOT = Path(tempfile.mkdtemp(prefix="apple-desk-path-hint-", dir="/tmp"))
FAKE_HOME = ROOT / "home"
FAKE_HOME.mkdir()
os.environ["HOME"] = str(FAKE_HOME)
os.environ["PATH"] = str(ROOT / "empty-path")
(ROOT / "empty-path").mkdir()

LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

import cli  # noqa: E402
import common  # noqa: E402

MARKER = "executed-forbidden"


def write_exec(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("#!/bin/sh\nprintf '%s'\nexit 9\n" % MARKER)
    path.chmod(0o755)


def snapshot(folder: Path) -> tuple:
    rows = []
    for path in sorted(folder.rglob("*")):
        rel = str(path.relative_to(folder))
        if path.is_symlink():
            rows.append((rel, "symlink", os.readlink(path)))
        elif path.is_file():
            stat = path.stat()
            rows.append((rel, "file", stat.st_size, stat.st_mode))
        else:
            rows.append((rel, "dir"))
    return tuple(rows)


def forbid_mutations() -> None:
    def boom(label):
        def _no(*_args, **_kwargs):
            raise AssertionError("mutated via " + label)

        return _no

    common.os.symlink = boom("symlink")
    common.os.link = boom("link")
    common.shutil.copy = boom("copy")
    common.shutil.copy2 = boom("copy2")
    common.shutil.copyfile = boom("copyfile")
    common.shutil.copytree = boom("copytree")
    common.shutil.move = boom("move")


def run_doctor(argv):
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


def main() -> None:
    failures = []

    def check(name, cond):
        if cond:
            print("ok", name)
        else:
            failures.append(name)
            print("FAIL", name)

    checkout = ROOT / "checkout"
    outside = ROOT / "outside"
    bin_dir = ROOT / "bin"
    later = ROOT / "later"
    inside_first = ROOT / "inside-first"
    not_a_dir = ROOT / "not-a-dir"
    write_exec(checkout / "cli" / "grok-notes" / "bin" / "grok-notes")
    write_exec(checkout / "cli" / "grok-mail" / "bin" / "grok-mail")
    write_exec(outside / "grok-notes")
    write_exec(outside / "grok-mail")
    quiet = outside / "grok-quiet"
    write_exec(quiet)
    quiet.chmod(0o644)
    bin_dir.mkdir()
    later.mkdir()
    inside_first.mkdir()
    (bin_dir / "grok-notes").symlink_to(outside / "grok-notes")
    (bin_dir / "grok-mail").symlink_to(outside / "grok-mail")
    (bin_dir / "grok-quiet").symlink_to(quiet)
    (bin_dir / "grok-folder").mkdir()
    (bin_dir / "other-tool").write_text("#!/bin/sh\nexit 0\n")
    (bin_dir / "other-tool").chmod(0o755)
    (later / "grok-notes").symlink_to(outside / "grok-notes")
    (inside_first / "grok-notes").symlink_to(checkout / "cli" / "grok-notes" / "bin" / "grok-notes")
    not_a_dir.write_text("not a directory\n")
    real_desk = common.checkout_root() / "cli" / "grok-desk" / "bin" / "grok-desk"
    real_link_dir = ROOT / "real-link"
    real_link_dir.mkdir()
    (real_link_dir / "grok-desk").symlink_to(real_desk)

    check("checkout root is this repo", common.checkout_root().name == "apple-desk")
    check("fake root is not the live home", LIVE_HOME not in str(ROOT) and str(FAKE_HOME) != LIVE_HOME)

    before = snapshot(ROOT)
    forbid_mutations()
    path_env = os.pathsep.join([str(not_a_dir), str(bin_dir)])
    hints = common.outside_checkout_hints(path_env=path_env, root=checkout)
    check("snapshot unchanged after hint", snapshot(ROOT) == before)
    check("two outside hints", len(hints) == 2)
    check("mail then notes", [line.split()[1] for line in hints] == ["grok-mail", "grok-notes"])
    notes = hints[1]
    check("names the path entry", str(bin_dir / "grok-notes") in notes)
    check("names the resolved target", str((outside / "grok-notes").resolve()) in notes)
    check("says outside this checkout", "resolves outside this checkout" in notes)
    check("says not relinked", notes.endswith("Not relinked."))
    check("no send step", all("send" not in line.lower() for line in hints))
    check("quiet non-executable is ignored", all("grok-quiet" not in line for line in hints))
    check("directory is ignored", all("grok-folder" not in line for line in hints))
    check("non-grok executable is ignored", all("other-tool" not in line for line in hints))
    check("hints do not contain the live home", all(LIVE_HOME not in line for line in hints) if LIVE_HOME else True)
    check("hint did not run the executable", all(MARKER not in line for line in hints))

    inside = common.outside_checkout_hints(path_env=str(inside_first), root=checkout)
    direct = common.outside_checkout_hints(
        path_env=str(checkout / "cli" / "grok-notes" / "bin"),
        root=checkout,
    )
    shadowed = common.outside_checkout_hints(
        path_env=os.pathsep.join([str(inside_first), str(later)]),
        root=checkout,
    )
    first_outside = common.outside_checkout_hints(
        path_env=os.pathsep.join([str(later), str(inside_first)]),
        root=checkout,
    )
    real_inside = common.outside_checkout_hints(path_env=str(real_link_dir), root=common.checkout_root())
    empty = common.outside_checkout_hints(path_env="", root=checkout)
    check("symlink into the checkout is quiet", inside == [])
    check("direct checkout binary is quiet", direct == [])
    check("later outside copy is not the PATH hit", shadowed == [])
    check(
        "first PATH hit outside is the hint",
        len(first_outside) == 1 and str((outside / "grok-notes").resolve()) in first_outside[0],
    )
    check("real checkout binary is quiet", real_inside == [])
    check("empty PATH is quiet", empty == [])
    check("still no files copied", snapshot(ROOT) == before)

    os.environ["PATH"] = str(bin_dir)
    cli.probe_tools = lambda: []
    cli.probe_caches = lambda: []
    expected = common.outside_checkout_hints(root=common.checkout_root())
    code, out, err = run_doctor(["doctor"])
    code_json, out_json, err_json = run_doctor(["doctor", "--json"])
    payload = json.loads(out_json)
    check("doctor exits 0", code == 0 and code_json == 0)
    check("doctor does not run the outside executable", MARKER not in out + err + out_json + err_json and err == "" and err_json == "")
    check("doctor prints each hint once", expected and all(out.count(line) == 1 for line in expected))
    check("json keeps ok and the same hints", payload.get("ok") is True and payload.get("pathHints") == expected)
    check("doctor hints stay off the live home", all(LIVE_HOME not in line for line in expected) if LIVE_HOME else True)
    check("doctor did not copy or relink", snapshot(ROOT) == before)
    shutil.rmtree(ROOT)

    if failures:
        print("failed:", ", ".join(failures))
        raise SystemExit(1)
    print("all ok")


if __name__ == "__main__":
    main()
