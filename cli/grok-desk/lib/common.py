"""Shared paths and file modes for grok-desk. Local only."""
from __future__ import annotations

import os
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

VERSION = "0.1.0"
TOOL = "grok-desk"
CHICAGO = ZoneInfo("America/Chicago")
APPLE = datetime(2001, 1, 1, tzinfo=timezone.utc)

# Calendar, Reminders, and Mail have timed out on Automation Allow.
# Never call them from onboard/reindex. Version check only.
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
    return datetime.now(CHICAGO).isoformat(timespec="seconds")


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
    return (APPLE + timedelta(seconds=seconds)).astimezone(CHICAGO).isoformat(timespec="seconds")


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


def which(name: str) -> str | None:
    found = shutil.which(name)
    if found:
        return found
    for folder in (Path.home() / "bin", Path.home() / ".local" / "bin"):
        candidate = folder / name
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def tool_sources(name: str) -> list[Path]:
    home = Path.home()
    return [
        home / "Developer" / name / "bin" / name,
        home / "Developer" / "apple-desk" / "cli" / name / "bin" / name,
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


def run_cmd(cmd: list[str], timeout: float) -> dict:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "timeout", "timeout": timeout}
    except OSError as exc:
        return {"ok": False, "error": "spawn_failed", "message": str(exc)}
    stdout = (proc.stdout or "").strip()
    stderr = (proc.stderr or "").strip()
    return {
        "ok": proc.returncode == 0,
        "code": proc.returncode,
        "stdout": stdout[:500],
        "stderr": stderr[:300],
    }


def version_of(path: str) -> str | None:
    result = run_cmd([path, "--version"], 5)
    text = (result.get("stdout") or result.get("stderr") or "").strip()
    if not text:
        return None
    return text.splitlines()[0][:120]
