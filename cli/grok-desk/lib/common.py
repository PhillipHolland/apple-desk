"""Shared paths and file modes for grok-desk. Local only."""
from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = "0.1.7"
TOOL = "grok-desk"
APPLE = datetime(2001, 1, 1, tzinfo=timezone.utc)

# Mail stays version-only: Mail.app doctor can hang. Cloud mail stays on the user's mail connector.
# Calendar and Reminders are not probed by the 5s onboard doctor loop.
# reindex calls each once with the CLI's own timeout. Timeout or deny -> pending_allow, no retry.
VERSION_ONLY = ("grok-calendar", "grok-reminders", "grok-mail")

TOOLS = (
    "grok-reminders",
    "grok-notes",
    "grok-contacts",
    "grok-messages",
    "grok-calendar",
    "grok-mail",
    "grok-shortcuts",
    "grok-icloud",
    "grok-spotlight",
    "grok-focus",
    "grok-safari",
)

CACHE_NAMES = ("grok-notes", "grok-messages", "grok-contacts", "grok-calendar", "grok-reminders")


def cache_dir(name: str) -> Path:
    return Path.home() / ".cache" / name


def db_path(name: str) -> Path:
    return cache_dir(name) / "index.sqlite"


def now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def apple_to_iso(value):
    if value is None:
        return None
    try:
        raw = int(value)
    except (TypeError, ValueError):
        return None
    if raw == 0:
        return None
    seconds = raw / 1e9 if abs(raw) > 10**12 else float(raw)
    return (APPLE + timedelta(seconds=seconds)).astimezone().isoformat(timespec="seconds")


def secure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    os.chmod(path, 0o700)


def secure_db(path: Path) -> None:
    if path.exists():
        os.chmod(path, 0o600)
    for extra in (str(path) + "-wal", str(path) + "-shm", str(path) + "-journal"):
        extra_path = Path(extra)
        if extra_path.exists():
            os.chmod(extra_path, 0o600)


def dir_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


def bundled(name: str) -> str | None:
    """CLI that ships beside grok-desk in this tree. Prefer it over a stale PATH link."""
    sibling = Path(__file__).resolve().parents[2] / name / "bin" / name
    if sibling.is_file() and os.access(sibling, os.X_OK):
        return str(sibling)
    return None


def which(name: str) -> str | None:
    found = bundled(name)
    if found:
        return found
    found = shutil.which(name)
    if found:
        return found
    for folder in (Path.home() / "bin", Path.home() / ".local" / "bin"):
        candidate = folder / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def checkout_root() -> Path:
    """Repo root for this grok-desk file (cli/grok-desk/lib -> apple-desk)."""
    return Path(__file__).resolve().parents[3]


def _path_inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except (ValueError, OSError):
        return False
    return True


def outside_checkout_hints(path_env: str | None = None, root: Path | None = None) -> list[str]:
    """Hint lines for grok-* executables on PATH that resolve outside this checkout.

    The first executable of each name wins, same as a shell search. Returns
    lines only: does not relink, copy, or run the executables.
    """
    if path_env is None:
        path_env = os.environ.get("PATH", "")
    root_path = checkout_root() if root is None else root
    found: dict[str, Path] = {}
    for folder in path_env.split(os.pathsep):
        if not folder:
            continue
        directory = Path(folder)
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            name = entry.name
            if not name.startswith("grok-") or name in found:
                continue
            try:
                executable = entry.is_file() and os.access(entry, os.X_OK)
            except OSError:
                continue
            if executable:
                found[name] = entry
    lines = []
    for name in sorted(found):
        entry = found[name]
        try:
            resolved = entry.resolve()
        except OSError:
            continue
        if _path_inside(resolved, root_path):
            continue
        lines.append(
            "hint: %s on PATH (%s) resolves outside this checkout (%s). Not relinked."
            % (name, entry, resolved)
        )
    return lines


def tool_sources(name: str) -> list[Path]:
    """Prefer the apple-desk checkout; fall back to a sibling ~/Developer/grok-* tree."""
    home = Path.home()
    return [
        home / "Developer" / "apple-desk" / "cli" / name / "bin" / name,
        home / "Developer" / name / "bin" / name,
    ]


def link_if_needed(name: str) -> dict:
    """Link into ~/bin and ~/.local/bin only when missing or broken."""
    src = next((p for p in tool_sources(name) if p.is_file() and os.access(p, os.X_OK)), None)
    linked = []
    kept = []
    skipped = src is None
    if src is not None:
        for folder in (Path.home() / "bin", Path.home() / ".local" / "bin"):
            folder.mkdir(parents=True, exist_ok=True)
            dest = folder / name
            if dest.exists() or dest.is_symlink():
                if os.access(dest, os.X_OK):
                    kept.append(str(dest))
                    continue
                dest.unlink()
            dest.symlink_to(src)
            linked.append(str(dest))
    return {"name": name, "source": str(src) if src else None, "linked": linked, "kept": kept, "skipped": skipped}


def run_cmd(cmd: list[str], timeout: float, stdout_limit: int = 500) -> dict:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "timeout": timeout}
    except OSError as exc:
        return {"ok": False, "error": "spawn_failed", "message": str(exc)}
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    limit = max(500, int(stdout_limit))
    return {
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "stdout": stdout[:limit],
        "stderr": stderr[:300],
    }


def version_of(path: str) -> str | None:
    result = run_cmd([path, "--version"], 5)
    text = (result.get("stdout") or result.get("stderr") or "").strip()
    if not text:
        return None
    return text.splitlines()[0][:120]


SIGNATURE_MAX = 160


def config_dir() -> Path:
    return Path.home() / ".config" / "grok-desk"


def signature_path() -> Path:
    return config_dir() / "signature"


def read_signature() -> str | None:
    """One stored line, or None when missing or unreadable."""
    path = signature_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return None
    line = raw.strip()
    if not line or any(ch < " " or ch == "\x7f" for ch in line):
        return None
    if len(line) > SIGNATURE_MAX:
        return None
    return line


def write_signature(text: str) -> str:
    line = (text or "").strip()
    if not line or any(ord(ch) < 32 or ord(ch) == 127 for ch in line) or len(line) > SIGNATURE_MAX:
        raise ValueError(
            "Signature must be one line, 1..%d characters, with no control characters." % SIGNATURE_MAX
        )
    folder = config_dir()
    secure_dir(folder)
    path = signature_path()
    path.write_text(line + "\n", encoding="utf-8")
    os.chmod(path, 0o600)
    return line


def clear_signature() -> None:
    path = signature_path()
    try:
        path.unlink()
    except FileNotFoundError:
        return
