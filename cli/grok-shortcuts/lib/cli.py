#!/usr/bin/env python3
"""grok-shortcuts: list, create, and run macOS Shortcuts.

run and create do nothing without --force. create signs a .shortcut on this Mac
with the local shortcuts CLI. It does not notarize through iCloud and does not
run the new shortcut.
"""
from __future__ import annotations

import argparse
import json
import plistlib
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

VERSION = "0.1.2"

GAPS = [
    "This wraps /usr/bin/shortcuts. It can list shortcuts and folders, run one shortcut by name, and create/sign one shortcut. It cannot edit or delete a shortcut, and it cannot build an arbitrary action graph.",
    "create without --force does nothing. create --dry-run validates only and never signs or opens Shortcuts. create --force signs locally (default mode people-who-know-me; override with --sign-mode anyone). Signing is not an iCloud notarization upload of your private library.",
    "Without --output, create --force opens the signed file in Shortcuts.app so you can confirm the add. That system confirm is separate from --force. With --output, the signed file is written and Shortcuts is not opened. The new shortcut is never run by create.",
    "A generated shortcut is one Comment action, plus an optional Show Result action when --text is set. Pass --from FILE.shortcut to sign a shortcut file you already have. The import name comes from --name, else the file stem.",
    "view opens Shortcuts.app on a shortcut. This CLI does not call view.",
    "run is not a dry read. A shortcut can send messages, place calls, toggle Home, write files, or anything else it was built to do. The wrapper does not inspect the shortcut graph, so it cannot tell a safe shortcut from a destructive one.",
    "run does nothing unless --force is present. Agents must not pass --force unless the user named that shortcut and accepted its side effects.",
    "There is no input builder beyond --input-path, and no way to pass a text stdin payload. Output goes to --output-path when the shortcut produces a file.",
    "Folder listing is names only. Identifiers need --show-identifiers and are opaque.",
    "Shortcuts iCloud sync can lag. A shortcut that exists on another device may be missing here until Shortcuts.app has downloaded it.",
    "No Voice Memos, dictation, or audio capture. Do not bolt those on.",
]

SIGN_MODES = ("anyone", "people-who-know-me")


def die(code, error, message, as_json):
    if as_json:
        print(json.dumps({
            "ok": False,
            "tool": "grok-shortcuts",
            "version": VERSION,
            "error": error,
            "code": code,
            "message": message,
        }))
    else:
        print(f"grok-shortcuts: {error}", file=sys.stderr)
        if message:
            print(message, file=sys.stderr)
    raise SystemExit(code)


def run_shortcuts(args, timeout):
    proc = subprocess.run(["shortcuts", *args], capture_output=True, text=True, timeout=timeout)
    return proc


def emit(data, as_json, text_fn):
    if not data.get("ok", False):
        code = 2 if data.get("error") in {
            "needs_force", "missing_name", "bad_request", "already_exists",
        } else 1
        if as_json:
            data.setdefault("tool", "grok-shortcuts")
            data.setdefault("version", VERSION)
            print(json.dumps(data))
        else:
            print(f"grok-shortcuts: {data.get('error')}: {data.get('message', '')}", file=sys.stderr)
        raise SystemExit(code)
    if as_json:
        data.setdefault("tool", "grok-shortcuts")
        data.setdefault("version", VERSION)
        print(json.dumps(data))
    else:
        text_fn(data)


def _lines(proc):
    if proc.returncode != 0:
        blob = (proc.stderr or proc.stdout or "shortcuts failed").strip()
        return None, blob
    lines = [line for line in (proc.stdout or "").splitlines() if line.strip()]
    return lines, None


def cmd_doctor(args):
    as_json = args.json
    try:
        proc = run_shortcuts(["list"], 30)
    except FileNotFoundError:
        die(1, "missing_cli", "/usr/bin/shortcuts is not on this Mac.", as_json)
    except subprocess.TimeoutExpired:
        die(4, "timeout", "shortcuts list timed out. Nothing was run.", as_json)
    lines, err = _lines(proc)
    if err is not None:
        die(1, "shortcuts_error", err, as_json)
    data = {
        "ok": True,
        "backend": "shortcuts-cli",
        "runRequiresForce": True,
        "createRequiresForce": True,
        "count": len(lines),
    }

    def text(d):
        print(f"grok-shortcuts {VERSION}  ok")
        print(f"shortcuts: {d['count']}")
        print("run: refused without --force (no shortcut was run)")
        print("create: refused without --force (no shortcut was signed or opened)")

    emit(data, as_json, text)


def cmd_list(args):
    as_json = args.json
    cmd = ["list"]
    if args.folders:
        cmd.append("--folders")
    if args.show_identifiers:
        cmd.append("--show-identifiers")
    if args.folder:
        cmd.extend(["--folder-name", args.folder])
    try:
        proc = run_shortcuts(cmd, 30)
    except subprocess.TimeoutExpired:
        die(4, "timeout", "shortcuts list timed out.", as_json)
    lines, err = _lines(proc)
    if err is not None:
        die(1, "shortcuts_error", err, as_json)
    data = {"ok": True, "folders": bool(args.folders), "count": len(lines), "names": lines}

    def text(d):
        kind = "folders" if d["folders"] else "shortcuts"
        print(f"{d['count']} {kind}")
        for name in d["names"]:
            print(name)

    emit(data, as_json, text)


def _installed_names(as_json):
    try:
        proc = run_shortcuts(["list"], 30)
    except FileNotFoundError:
        die(1, "missing_cli", "/usr/bin/shortcuts is not on this Mac.", as_json)
    except subprocess.TimeoutExpired:
        die(4, "timeout", "shortcuts list timed out. Nothing was created.", as_json)
    lines, err = _lines(proc)
    if err is not None:
        die(1, "shortcuts_error", err, as_json)
    return lines


def _clean_name(raw, as_json):
    name = (raw or "").strip()
    if not name or len(name) > 80:
        die(2, "bad_request", "Pass a shortcut name of 1 to 80 characters. Nothing was created.", as_json)
    bad = {"/", chr(92), chr(0)}
    if any(ch in name for ch in bad) or name in {".", ".."}:
        die(2, "bad_request", "The name cannot be a path. Nothing was created.", as_json)
    return name


def _comment_workflow(name, comment, show_text):
    actions = [{
        "WFWorkflowActionIdentifier": "is.workflow.actions.comment",
        "WFWorkflowActionParameters": {
            "UUID": str(uuid.uuid4()).upper(),
            "WFCommentActionText": comment,
        },
    }]
    if show_text:
        actions.append({
            "WFWorkflowActionIdentifier": "is.workflow.actions.showresult",
            "WFWorkflowActionParameters": {
                "UUID": str(uuid.uuid4()).upper(),
                "Text": show_text,
            },
        })
    return {
        "WFWorkflowClientVersion": "2700.0.4",
        "WFWorkflowClientRelease": "2700",
        "WFWorkflowMinimumClientVersion": 900,
        "WFWorkflowMinimumClientVersionString": "900",
        "WFWorkflowName": name,
        "WFWorkflowIcon": {
            "WFWorkflowIconStartColor": 4282601983,
            "WFWorkflowIconGlyphNumber": 59511,
        },
        "WFWorkflowTypes": [],
        "WFWorkflowInputContentItemClasses": ["WFStringContentItem"],
        "WFWorkflowImportQuestions": [],
        "WFWorkflowHasOutputFallback": False,
        "WFWorkflowOutputContentItemClasses": [],
        "WFWorkflowActions": actions,
    }


def _sign(src, dest, mode, as_json):
    try:
        proc = run_shortcuts([
            "sign", "--mode", mode,
            "--input", str(src), "--output", str(dest),
        ], 45)
    except subprocess.TimeoutExpired:
        die(4, "timeout", "shortcuts sign timed out. Nothing was opened.", as_json)
    if proc.returncode != 0 or not Path(dest).is_file():
        blob = (proc.stderr or proc.stdout or "shortcuts sign failed").strip()
        die(1, "shortcuts_error", blob[:400], as_json)


def _cache_dir():
    path = Path.home() / ".cache" / "grok-shortcuts"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cmd_create(args):
    as_json = args.json
    source = (args.from_file or "").strip()
    comment = (args.comment or "").strip()
    show_text = (args.text or "").strip()
    mode = (args.sign_mode or "people-who-know-me").strip()
    if mode not in SIGN_MODES:
        die(2, "bad_request", "--sign-mode must be anyone or people-who-know-me. Nothing was created.", as_json)
    if source and (comment or show_text):
        die(2, "bad_request", "Pass either --from or --comment/--text, not both. Nothing was created.", as_json)
    if not source and not comment:
        die(2, "bad_request", "create needs --comment, or --from FILE.shortcut. Nothing was created.", as_json)
    if comment and len(comment) > 2000:
        die(2, "bad_request", "--comment must be 2000 characters or fewer. Nothing was created.", as_json)
    if show_text and len(show_text) > 500:
        die(2, "bad_request", "--text must be 500 characters or fewer. Nothing was created.", as_json)
    if source:
        src_path = Path(source).expanduser()
        if src_path.suffix != ".shortcut" or not src_path.is_file():
            die(2, "bad_request", "--from must be an existing .shortcut file. Nothing was created.", as_json)
        name = _clean_name(args.name or src_path.stem, as_json)
    else:
        name = _clean_name(args.name, as_json)
        src_path = None
    names = _installed_names(as_json)
    if name in names:
        die(2, "already_exists", f"A shortcut named {name!r} is already installed. Nothing was created.", as_json)

    # Dry-run / gate: never sign or open.
    if args.dry_run or not args.force:
        if not args.force and not args.dry_run:
            die(
                2,
                "needs_force",
                f"Refusing to create {name!r} without --force. Nothing was signed or opened.",
                as_json,
            )
        # Validate generated plist builds when not --from.
        built = False
        if src_path is None:
            blob = plistlib.dumps(_comment_workflow(name, comment, show_text), fmt=plistlib.FMT_XML)
            built = True
            if len(blob) < 64:
                die(1, "shortcuts_error", "Failed to build a shortcut plist. Nothing was created.", as_json)
        data = {
            "ok": True,
            "dryRun": True,
            "created": False,
            "signed": False,
            "opened": False,
            "name": name,
            "fromFile": bool(source),
            "signMode": mode,
            "plistBuilt": built,
            "message": "dry-run: shortcut was not signed or opened.",
        }
        emit(data, as_json, lambda d: print(f"dry-run create {d['name']!r} (not signed)"))
        return

    tmp = Path(tempfile.mkdtemp(prefix="grok-shortcuts-", dir=str(_cache_dir())))
    unsigned = tmp / "unsigned.shortcut"
    try:
        if src_path is not None:
            unsigned.write_bytes(src_path.read_bytes())
        else:
            unsigned.write_bytes(
                plistlib.dumps(_comment_workflow(name, comment, show_text), fmt=plistlib.FMT_XML)
            )
        if args.output:
            dest = Path(args.output).expanduser()
            if dest.suffix != ".shortcut":
                die(2, "bad_request", "--output must end in .shortcut. Nothing was created.", as_json)
            dest.parent.mkdir(parents=True, exist_ok=True)
            opened = False
        else:
            dest = tmp / f"{name}.shortcut"
            opened = True
        _sign(unsigned, dest, mode, as_json)
        if opened:
            try:
                subprocess.run(["/usr/bin/open", "-a", "Shortcuts", str(dest)], check=False, timeout=15)
            except (OSError, subprocess.TimeoutExpired) as exc:
                die(1, "open_failed", f"Signed file is at {dest} but Shortcuts did not open ({exc}).", as_json)
        else:
            # Keep only the requested output; drop the temp workspace.
            shutil.rmtree(tmp, ignore_errors=True)
        data = {
            "ok": True,
            "created": True,
            "signed": True,
            "opened": opened,
            "name": name,
            "mode": mode,
            "output": str(dest),
            "ran": False,
            "message": (
                "Signed locally. Shortcuts.app was asked to add it; confirm there if a prompt is up. The shortcut was not run."
                if opened else
                "Signed locally to --output. It was not opened and not run. Import is a separate step."
            ),
        }

        def text(d):
            print(d["message"])
            print(f"name: {d['name']}")
            print(f"file: {d['output']}")

        emit(data, as_json, text)
    except SystemExit:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(tmp, ignore_errors=True)
        raise


def cmd_run(args):
    as_json = args.json
    name = (args.name or "").strip()
    if not name:
        die(2, "missing_name", "Pass the shortcut name. Nothing was run.", as_json)
    if args.dry_run:
        try:
            proc = run_shortcuts(["list"], 30)
        except subprocess.TimeoutExpired:
            die(4, "timeout", "shortcuts list timed out. Nothing was run.", as_json)
        lines, err = _lines(proc)
        if err is not None:
            die(1, "shortcuts_error", err, as_json)
        found = name in lines
        data = {
            "ok": True,
            "dryRun": True,
            "ran": False,
            "name": name,
            "installed": found,
            "message": "dry-run: shortcut was not run.",
        }
        emit(data, as_json, lambda d: print(f"dry-run {d['name']!r} installed={d['installed']} (not run)"))
        return
    if not args.force:
        die(
            2,
            "needs_force",
            f"Refusing to run {name!r} without --force. A shortcut can message, call, change Home, or write files. Nothing was run.",
            as_json,
        )
    cmd = ["run", name]
    for path in args.input_path or []:
        cmd.extend(["--input-path", path])
    if args.output_path:
        cmd.extend(["--output-path", args.output_path])
    if args.output_type:
        cmd.extend(["--output-type", args.output_type])
    try:
        proc = run_shortcuts(cmd, args.timeout)
    except subprocess.TimeoutExpired:
        die(4, "timeout", f"shortcuts run timed out after {args.timeout}s.", as_json)
    if proc.returncode != 0:
        blob = (proc.stderr or proc.stdout or "shortcuts run failed").strip()
        die(1, "shortcuts_error", blob, as_json)
    data = {
        "ok": True,
        "ran": True,
        "name": name,
        "stdout": (proc.stdout or "")[:4000],
    }

    def text(d):
        print(f"ran {d['name']}")
        if d["stdout"].strip():
            print(d["stdout"].rstrip())

    emit(data, as_json, text)


def cmd_gaps(args):
    as_json = getattr(args, "json", False)
    data = {"ok": True, "tool": "grok-shortcuts", "version": VERSION, "gaps": GAPS}
    if as_json:
        print(json.dumps(data))
        return
    print("grok-shortcuts gaps")
    for item in GAPS:
        print(f"- {item}")


def build_parser():
    parser = argparse.ArgumentParser(prog="grok-shortcuts", description="List, create, and run macOS Shortcuts")
    parser.add_argument("--version", action="version", version=f"grok-shortcuts {VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_json(p):
        p.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor")
    add_json(doctor)
    doctor.set_defaults(func=cmd_doctor)

    listing = sub.add_parser("list")
    add_json(listing)
    listing.add_argument("--folders", action="store_true")
    listing.add_argument("--show-identifiers", action="store_true")
    listing.add_argument("--folder")
    listing.set_defaults(func=cmd_list)

    create = sub.add_parser("create", help="Sign one shortcut. Does nothing without --force.")
    add_json(create)
    create.add_argument("--name", help="Shortcut name. Defaults to the --from file stem.")
    create.add_argument("--comment", help="Comment action text for a generated shortcut.")
    create.add_argument("--text", help="Optional Show Result text. Not a message send.")
    create.add_argument("--from", dest="from_file", help="Existing .shortcut file to sign.")
    create.add_argument("--output", help="Write the signed file here and do not open Shortcuts.")
    create.add_argument(
        "--sign-mode",
        choices=list(SIGN_MODES),
        default="people-who-know-me",
        help="shortcuts sign mode (default: people-who-know-me).",
    )
    create.add_argument("--dry-run", action="store_true", help="Validate only. Does not sign or open.")
    create.add_argument("--force", action="store_true", help="Allow signing. Does not run the shortcut.")
    create.set_defaults(func=cmd_create)

    run = sub.add_parser("run")
    add_json(run)
    run.add_argument("name")
    run.add_argument("--force", action="store_true")
    run.add_argument("--dry-run", action="store_true", help="Check the name is installed. Does not run it.")
    run.add_argument("--input-path", action="append")
    run.add_argument("--output-path")
    run.add_argument("--output-type")
    run.add_argument("--timeout", type=int, default=60)
    run.set_defaults(func=cmd_run)

    gaps = sub.add_parser("gaps")
    add_json(gaps)
    gaps.set_defaults(func=cmd_gaps)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    timeout = getattr(args, "timeout", None)
    if isinstance(timeout, int) and not 1 <= timeout <= 300:
        die(2, "bad_request", "--timeout must be 1 through 300 seconds.", getattr(args, "json", False))
    try:
        args.func(args)
    except BrokenPipeError:
        raise SystemExit(0)


if __name__ == "__main__":
    main()
