"""Shared paths and file modes for grok-desk. Local only."""
from __future__ import annotations

import os
import json
import signal
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERSION = "0.2.0"
TOOL = "grok-desk"
APPLE = datetime(2001, 1, 1, tzinfo=timezone.utc)

# Legacy doctors can send Apple Events and therefore show permission prompts.
# Passive desk status checks only the new no-prompt Mail/EventKit doctors.
VERSION_ONLY = ("grok-reminders", "grok-notes", "grok-contacts", "grok-messages",
                "grok-shortcuts", "grok-icloud", "grok-spotlight", "grok-focus", "grok-safari")

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
    """Bound a process group so a timed-out facade cannot leave its helper running."""
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, start_new_session=True)
    except OSError as exc:
        return {"ok": False, "error": "spawn_failed", "message": str(exc)}
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            proc.communicate(timeout=1)
        except subprocess.TimeoutExpired:
            pass
        return {"ok": False, "error": "timeout", "timeout": timeout}
    stdout, stderr = (stdout or "").strip(), (stderr or "").strip()
    limit = max(500, int(stdout_limit))
    return {"ok": proc.returncode == 0, "code": proc.returncode,
            "stdout": stdout[:limit], "stdoutTruncated": len(stdout) > limit, "stderr": stderr[:300]}


def unwrap_result(result: dict) -> dict:
    """Read a tool envelope; successful process exit alone never implies success."""
    if result.get("error"):
        return {"ok": False, "error": result["error"], "message": result.get("message") or result["error"], "data": {}}
    try:
        payload = json.loads(result.get("stdout") or "")
        if not isinstance(payload, dict) or result.get("stdoutTruncated"):
            raise ValueError("invalid envelope")
    except (ValueError, TypeError):
        return {"ok": False, "error": "invalid_response", "message": "The tool did not return a complete JSON object.", "data": {}}
    normalized = "schemaVersion" in payload
    data = payload.get("data") if normalized else payload
    error = payload.get("error")
    if isinstance(error, dict):
        code, message = error.get("code"), error.get("message")
    else:
        code, message = error, payload.get("message")
    success = result.get("ok") is True and payload.get("ok") is True
    return {"ok": success, "data": data if isinstance(data, dict) else {},
            "error": None if success else (code or "cli_failed"),
            "message": message or (result.get("stderr") or ""), "exitCode": result.get("code"),
            "normalized": normalized}


def version_of(path: str) -> str | None:
    result = run_cmd([path, "--version"], 5, stdout_limit=16000)
    raw = (result.get("stdout") or result.get("stderr") or "").strip()
    if not raw:
        return None
    if raw.startswith("{"):
        decoded = unwrap_result(result)
        data = decoded.get("data") or {}
        version = data.get("version")
        if version is not None:
            return str(version)[:120]
        try:
            return str((json.loads(raw).get("meta") or {}).get("version") or "unknown")[:120]
        except (ValueError, TypeError):
            return None
    return raw.splitlines()[0][:120]


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
