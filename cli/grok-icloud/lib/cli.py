#!/usr/bin/env python3
"""grok-icloud: read the local iCloud Drive folder. Does not download evicted files."""
from __future__ import annotations

import argparse
import fnmatch
import json
import os
import sys
from pathlib import Path

VERSION = "0.1.0"
TOOL = "grok-icloud"
# UF_DATALESS on APFS. A dataless file is an iCloud placeholder that is not on disk.
UF_DATALESS = 0x40000000
SKIP_NAMES = {".Trash", ".TemporaryItems"}
ROOT = Path.home() / "Library/Mobile Documents/com~apple~CloudDocs"
TEXT_EXTENSIONS = {
    ".txt", ".md", ".markdown", ".csv", ".tsv", ".json", ".jsonl", ".opml",
    ".xml", ".html", ".htm", ".css", ".js", ".ts", ".py", ".sh", ".yaml",
    ".yml", ".toml", ".ini", ".cfg", ".log", ".rtf", ".tex", ".svg",
}

GAPS = [
    "This is a Finder-class view of the iCloud Drive folder at ~/Library/Mobile Documents/com~apple~CloudDocs. It is not iCloud.com, not CloudKit, and not the other ubiquity containers under ~/Library/Mobile Documents (app libraries, Mail, Messages).",
    "Evicted files stay evicted. A dataless file (UF_DATALESS) or a name ending in .icloud is reported as evicted and is never opened. There is no download flag in 0.1.0. brctl, fileproviderctl, and osascript are not called.",
    "cat reads only a file that is already local, looks like text, and is within --max-bytes (default 8192, hard cap 65536). Anything else is refused with no body. It does not materialize a placeholder.",
    "doctor, tree, and find are depth- and count-capped. They skip .Trash and .TemporaryItems unless that directory is the path you named. They do not walk the whole drive.",
    "A folder named Desktop or Documents inside iCloud Drive is not the Mac Desktop or Documents folder unless those two paths are the same directory. doctor reports that separately. This CLI does not turn Desktop & Documents sync on or off.",
    "Symlinks are listed and not followed when the target leaves CloudDocs. No upload, delete, move, rename, share, or version check. Local does not mean latest.",
    "No Keychain, Passwords, Mail stores, or Messages. Do not point this tool at them; paths outside CloudDocs are refused.",
]


def die(code, error, message, as_json):
    payload = {
        "ok": False,
        "tool": TOOL,
        "version": VERSION,
        "error": error,
        "code": code,
        "message": message,
    }
    if as_json:
        print(json.dumps(payload))
    else:
        print(f"{TOOL}: {error}", file=sys.stderr)
        if message:
            print(message, file=sys.stderr)
    raise SystemExit(code)


def emit(data, as_json, text_fn):
    if not data.get("ok", False):
        soft = {
            "bad_request", "not_found", "escapes_root", "not_a_directory",
            "not_a_file", "evicted", "not_text", "oversized", "binary",
        }
        code = 2 if data.get("error") in soft else 1
        if as_json:
            data.setdefault("tool", TOOL)
            data.setdefault("version", VERSION)
            data.setdefault("code", code)
            data.setdefault("message", "")
            print(json.dumps(data))
        else:
            print(f"{TOOL}: {data.get('error')}: {data.get('message', '')}", file=sys.stderr)
        raise SystemExit(code)
    if as_json:
        data.setdefault("tool", TOOL)
        data.setdefault("version", VERSION)
        print(json.dumps(data))
    else:
        text_fn(data)


def root_resolved():
    try:
        return ROOT.resolve()
    except OSError:
        return ROOT


def same_dir(a: Path, b: Path) -> bool:
    try:
        if not a.exists() or not b.exists():
            return False
        sa, sb = a.stat(), b.stat()
    except OSError:
        return False
    return sa.st_dev == sb.st_dev and sa.st_ino == sb.st_ino


def desktop_documents():
    home = Path.home()
    cloud_desktop = ROOT / "Desktop"
    cloud_documents = ROOT / "Documents"
    home_desktop_in = same_dir(home / "Desktop", cloud_desktop)
    home_documents_in = same_dir(home / "Documents", cloud_documents)
    return {
        "enabled": home_desktop_in or home_documents_in,
        "homeDesktopInCloud": home_desktop_in,
        "homeDocumentsInCloud": home_documents_in,
        "cloudDesktopFolder": cloud_desktop.is_dir(),
        "cloudDocumentsFolder": cloud_documents.is_dir(),
    }


def classify(ent):
    name = ent.name
    kind = "other"
    if ent.is_symlink():
        kind = "symlink"
    elif ent.is_dir(follow_symlinks=False):
        kind = "dir"
    elif ent.is_file(follow_symlinks=False):
        kind = "file"
    state = "local"
    size = None
    try:
        st = ent.stat(follow_symlinks=False)
        size = st.st_size
        flags = getattr(st, "st_flags", 0) or 0
        if flags & UF_DATALESS or name.endswith(".icloud"):
            state = "evicted"
    except OSError:
        state = "unreadable"
    if name.endswith(".icloud"):
        state = "evicted"
        kind = "placeholder" if kind == "file" else kind
    return {
        "name": name,
        "kind": kind,
        "state": state,
        "bytes": size,
    }


def resolve_user_path(rel, as_json, must_exist=True):
    if not ROOT.is_dir():
        die(1, "missing_root", f"{ROOT} is not a directory.", as_json)
    if rel is None or rel == "" or rel == ".":
        return root_resolved(), ""
    raw = Path(rel).expanduser()
    candidate = raw if raw.is_absolute() else ROOT / raw
    try:
        resolved = candidate.resolve(strict=False)
    except OSError as exc:
        die(1, "io_error", str(exc), as_json)
    base = root_resolved()
    if resolved != base and base not in resolved.parents:
        die(2, "escapes_root", "That path is outside iCloud Drive. Nothing was read.", as_json)
    if must_exist and not candidate.exists() and not candidate.is_symlink():
        # exists() follows a final symlink; a dangling link is still "there" via is_symlink on the leaf.
        die(2, "not_found", "No such file or folder in iCloud Drive.", as_json)
    if must_exist and not resolved.exists() and not candidate.is_symlink():
        die(2, "not_found", "No such file or folder in iCloud Drive.", as_json)
    relpath = "" if resolved == base else resolved.relative_to(base).as_posix()
    return resolved, relpath


def clamp(n, default, lo, hi, as_json, flag):
    if n is None:
        return default
    if n < lo or n > hi:
        die(2, "bad_request", f"{flag} must be {lo}..{hi}.", as_json)
    return n


def skipped(name: str) -> bool:
    return name in SKIP_NAMES


def cmd_doctor(args):
    as_json = args.json
    if not ROOT.exists():
        die(1, "missing_root", f"{ROOT} does not exist.", as_json)
    if not ROOT.is_dir():
        die(1, "missing_root", f"{ROOT} is not a directory.", as_json)
    readable = os.access(ROOT, os.R_OK)
    if not readable:
        die(1, "not_readable", f"{ROOT} is not readable.", as_json)
    max_depth = 2
    max_nodes = 2000
    nodes = 0
    capped = False
    counts = {
        "directories": 0,
        "filesLocal": 0,
        "filesEvicted": 0,
        "placeholders": 0,
        "symlinks": 0,
        "other": 0,
        "unreadable": 0,
    }
    stack = [(ROOT, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            iterator = os.scandir(current)
        except OSError:
            counts["unreadable"] += 1
            continue
        with iterator:
            children = []
            for ent in iterator:
                if nodes >= max_nodes:
                    capped = True
                    break
                nodes += 1
                info = classify(ent)
                if info["kind"] == "dir":
                    counts["directories"] += 1
                    if depth + 1 < max_depth and not skipped(ent.name) and info["state"] != "evicted":
                        children.append(ent.path)
                elif info["kind"] == "placeholder":
                    counts["placeholders"] += 1
                elif info["kind"] == "symlink":
                    counts["symlinks"] += 1
                elif info["kind"] == "file":
                    if info["state"] == "evicted":
                        counts["filesEvicted"] += 1
                    else:
                        counts["filesLocal"] += 1
                else:
                    counts["other"] += 1
            if capped:
                break
            for child in children:
                stack.append((Path(child), depth + 1))
        if capped:
            break
    data = {
        "ok": True,
        "backend": "filesystem",
        "downloads": False,
        "root": str(ROOT),
        "exists": True,
        "readable": True,
        "desktopDocuments": desktop_documents(),
        "estimate": {
            "maxDepth": max_depth,
            "maxNodes": max_nodes,
            "nodesVisited": nodes,
            "capped": capped,
            **counts,
        },
    }

    def text(d):
        est = d["estimate"]
        desk = d["desktopDocuments"]
        print(f"grok-icloud {VERSION}  ok")
        print(f"root: {d['root']}")
        print("downloads: no (evicted files are not opened)")
        sync = "on" if desk["enabled"] else "off"
        print(f"desktop & documents sync: {sync}")
        print(
            "estimate depth {maxDepth}: dirs {directories}  local {filesLocal}  "
            "evicted {filesEvicted}  placeholders {placeholders}  symlinks {symlinks}".format(**est)
        )
        if est["capped"]:
            print(f"(stopped at {est['maxNodes']} entries)")

    emit(data, as_json, text)


def cmd_ls(args):
    as_json = args.json
    limit = clamp(args.limit, 100, 1, 500, as_json, "--limit")
    path, rel = resolve_user_path(args.relpath, as_json)
    if path.is_symlink():
        die(2, "escapes_root", "Refusing to follow a symlink. Name the real folder inside iCloud Drive.", as_json)
    if not path.is_dir():
        die(2, "not_a_directory", "ls needs a folder.", as_json)
    rows = []
    try:
        iterator = os.scandir(path)
    except OSError as exc:
        die(1, "io_error", str(exc), as_json)
    with iterator:
        for ent in iterator:
            info = classify(ent)
            info["relpath"] = f"{rel}/{info['name']}" if rel else info["name"]
            rows.append(info)
    rows.sort(key=lambda r: (r["kind"] != "dir", r["name"].casefold()))
    truncated = len(rows) > limit
    shown = rows[:limit]
    data = {
        "ok": True,
        "relpath": rel,
        "count": len(rows),
        "returned": len(shown),
        "truncated": truncated,
        "entries": shown,
    }

    def text(d):
        label = d["relpath"] or "."
        print(f"{d['returned']} of {d['count']} in {label}")
        for row in d["entries"]:
            state = row["state"]
            kind = row["kind"]
            size = "-" if row["bytes"] is None else row["bytes"]
            print(f"  {kind:11} {state:10} {size:>10}  {row['name']}")
        if d["truncated"]:
            print("(truncated; raise --limit)")

    emit(data, as_json, text)


def cmd_tree(args):
    as_json = args.json
    depth = clamp(args.depth, 2, 0, 4, as_json, "--depth")
    path, rel = resolve_user_path(args.relpath, as_json)
    if not path.is_dir() or path.is_symlink():
        die(2, "not_a_directory", "tree needs a real folder inside iCloud Drive.", as_json)
    budget = 500
    used = 0
    capped = False

    def walk(directory: Path, relpath: str, level: int):
        nonlocal used, capped
        nodes = []
        if level >= depth:
            return nodes
        try:
            iterator = os.scandir(directory)
        except OSError:
            return [{"relpath": relpath, "kind": "dir", "state": "unreadable", "name": directory.name}]
        with iterator:
            entries = list(iterator)
        entries.sort(key=lambda e: (not e.is_dir(follow_symlinks=False), e.name.casefold()))
        for ent in entries:
            if used >= budget:
                capped = True
                break
            if skipped(ent.name):
                continue
            used += 1
            info = classify(ent)
            child_rel = f"{relpath}/{info['name']}" if relpath else info["name"]
            info["relpath"] = child_rel
            if info["kind"] == "dir" and info["state"] != "evicted" and not ent.is_symlink() and level + 1 < depth:
                info["children"] = walk(Path(ent.path), child_rel, level + 1)
            nodes.append(info)
        return nodes

    nodes = walk(path, rel, 0)
    data = {
        "ok": True,
        "relpath": rel,
        "depth": depth,
        "nodesVisited": used,
        "truncated": capped,
        "entries": nodes,
    }

    def text(d):
        print(f"tree {d['relpath'] or '.'} depth {d['depth']}  ({d['nodesVisited']} nodes)")

        def rec(items, indent):
            for row in items:
                print(f"{indent}{row['kind']:11} {row['state']:10} {row['name']}")
                rec(row.get("children") or [], indent + "  ")

        rec(d["entries"], "  ")
        if d["truncated"]:
            print("(truncated)")

    emit(data, as_json, text)


def name_matches(name: str, pattern: str) -> bool:
    folded = name.casefold()
    pat = pattern.casefold()
    if any(ch in pattern for ch in "*?["):
        return fnmatch.fnmatch(folded, pat)
    return pat in folded


def cmd_find(args):
    as_json = args.json
    pattern = (args.pattern or "").strip()
    if not pattern:
        die(2, "bad_request", "Pass a name or glob. Nothing was searched.", as_json)
    if len(pattern) > 200:
        die(2, "bad_request", "Pattern is too long.", as_json)
    limit = clamp(args.limit, 50, 1, 200, as_json, "--limit")
    path, rel = resolve_user_path(args.relpath, as_json)
    if not path.is_dir() or path.is_symlink():
        die(2, "not_a_directory", "find starts at a real folder inside iCloud Drive.", as_json)
    matches = []
    visited = 0
    capped = False
    walk_capped = False
    max_visit = 8000
    max_depth = 6
    base = root_resolved()
    stack = [path]
    while stack:
        current = stack.pop()
        depth = len(current.parts) - len(path.parts)
        try:
            iterator = os.scandir(current)
        except OSError:
            continue
        with iterator:
            entries = list(iterator)
        entries.sort(key=lambda ent: ent.name.casefold())
        child_dirs = []
        for ent in entries:
            visited += 1
            if visited > max_visit:
                walk_capped = True
                break
            info = classify(ent)
            if name_matches(ent.name, pattern):
                parent = "" if current == base else current.relative_to(base).as_posix()
                info["relpath"] = f"{parent}/{ent.name}" if parent else ent.name
                matches.append(info)
                if len(matches) >= limit:
                    capped = True
                    break
            if (
                info["kind"] == "dir"
                and info["state"] != "evicted"
                and not ent.is_symlink()
                and not skipped(ent.name)
                and depth + 1 < max_depth
            ):
                child_dirs.append(Path(ent.path))
        if capped or walk_capped:
            break
        stack.extend(reversed(child_dirs))
    data = {
        "ok": True,
        "pattern": pattern,
        "relpath": rel,
        "returned": len(matches),
        "truncated": capped,
        "walkCapped": walk_capped,
        "visited": visited,
        "matches": matches,
    }

    def text(d):
        print(f"{d['returned']} match(es) for {d['pattern']!r}")
        for row in d["matches"]:
            print(f"  {row['kind']:11} {row['state']:10} {row['relpath']}")
        if d["truncated"] or d["walkCapped"]:
            print("(capped)")

    emit(data, as_json, text)


def looks_binary(data: bytes) -> bool:
    if b"\x00" in data:
        return True
    weird = 0
    for byte in data:
        if byte in (9, 10, 13):
            continue
        if byte < 32 or byte == 127:
            weird += 1
    return weird > max(8, len(data) // 20)


def cmd_cat(args):
    as_json = args.json
    if not args.relpath:
        die(2, "bad_request", "Pass the file path. Nothing was read.", as_json)
    max_bytes = clamp(args.max_bytes, 8192, 1, 65536, as_json, "--max-bytes")
    path, rel = resolve_user_path(args.relpath, as_json)
    if path.is_symlink():
        die(2, "escapes_root", "Refusing to follow a symlink.", as_json)
    if path.is_dir():
        die(2, "not_a_file", "cat needs a file.", as_json)
    if not path.is_file():
        die(2, "not_a_file", "Not a file.", as_json)
    try:
        st = path.lstat()
    except OSError as exc:
        die(1, "io_error", str(exc), as_json)
    flags = getattr(st, "st_flags", 0) or 0
    if flags & UF_DATALESS or path.name.endswith(".icloud"):
        die(
            2,
            "evicted",
            "That file is not downloaded (dataless or .icloud). It was not opened and will not be downloaded.",
            as_json,
        )
    suffix = path.suffix.lower()
    binary_suffixes = {
        ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".heic", ".tif", ".tiff", ".zip",
        ".pages", ".numbers", ".key", ".docx", ".xlsx", ".pptx", ".mov", ".mp4",
        ".m4a", ".mp3", ".wav", ".ai", ".psd", ".dmg", ".pkg", ".app",
        ".sqlite", ".db", ".gz", ".tgz", ".bz2", ".xz", ".rar", ".7z", ".data",
    }
    if suffix in binary_suffixes:
        die(2, "binary", f"Refusing {suffix} (not plain text). Nothing was read.", as_json)
    if st.st_size > max_bytes:
        die(
            2,
            "oversized",
            f"File is {st.st_size} bytes, over the {max_bytes} byte cap. Nothing was read. Raise --max-bytes (max 65536) only for a file you expect to be text.",
            as_json,
        )
    try:
        with path.open("rb") as handle:
            blob = handle.read(max_bytes + 1)
    except OSError as exc:
        die(1, "io_error", str(exc), as_json)
    if looks_binary(blob):
        die(2, "binary", "Refusing a binary file. Nothing is printed.", as_json)
    raw = blob[:max_bytes]
    encoding = "utf-8"
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        # Old Mac text and RTF are often not UTF-8. Only after the binary sniff.
        if suffix in TEXT_EXTENSIONS or suffix in {"", ".text"}:
            text = raw.decode("latin-1")
            encoding = "latin-1"
        else:
            die(2, "not_text", "File is not UTF-8 text. Nothing is printed.", as_json)
    data = {
        "ok": True,
        "relpath": rel,
        "bytes": st.st_size,
        "bytesRead": min(st.st_size, max_bytes),
        "truncated": len(blob) > max_bytes,
        "encoding": encoding,
        "text": text,
    }

    def show(d):
        sys.stdout.write(d["text"])
        if d["text"] and not d["text"].endswith("\n"):
            sys.stdout.write("\n")

    emit(data, as_json, show)


def cmd_gaps(_args):
    print("grok-icloud gaps")
    for item in GAPS:
        print(f"- {item}")


def build_parser():
    parser = argparse.ArgumentParser(
        prog="grok-icloud",
        description="List the local iCloud Drive folder. Does not download evicted files.",
    )
    parser.add_argument("--version", action="version", version=f"grok-icloud {VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_json(p):
        p.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor")
    add_json(doctor)
    doctor.set_defaults(func=cmd_doctor)

    listing = sub.add_parser("ls")
    add_json(listing)
    listing.add_argument("relpath", nargs="?")
    listing.add_argument("--limit", type=int)
    listing.set_defaults(func=cmd_ls)

    tree = sub.add_parser("tree")
    add_json(tree)
    tree.add_argument("relpath", nargs="?")
    tree.add_argument("--depth", type=int)
    tree.set_defaults(func=cmd_tree)

    find = sub.add_parser("find")
    add_json(find)
    find.add_argument("pattern")
    find.add_argument("relpath", nargs="?")
    find.add_argument("--limit", type=int)
    find.set_defaults(func=cmd_find)

    cat = sub.add_parser("cat")
    add_json(cat)
    cat.add_argument("relpath")
    cat.add_argument("--max-bytes", type=int)
    cat.set_defaults(func=cmd_cat)

    gaps = sub.add_parser("gaps")
    gaps.set_defaults(func=cmd_gaps)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except BrokenPipeError:
        raise SystemExit(0)


if __name__ == "__main__":
    main()
