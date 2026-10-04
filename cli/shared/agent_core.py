"""Private local state and the Apple Desk agent protocol (standard library only)."""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import stat
import tempfile

VERSION = "0.2.0"
SCHEMA_VERSION = "1.0"


class ToolError(Exception):
    def __init__(self, code, message, details=None, data=None):
        super().__init__(message)
        self.code, self.message = code, message
        self.details, self.data = details or {}, data
        if code in {"TIMEOUT", "BUSY", "MAIL_NOT_RUNNING", "APP_NOT_RUNNING"}:
            self.exit_code = 5
        elif code.endswith("STATUS_UNKNOWN"):
            self.exit_code = 6
        elif "PERMISSION" in code or code in {"NOT_AUTHORIZED", "ACCESS_DENIED"}:
            self.exit_code = 3
        elif code in {"NOT_FOUND", "STALE_REFERENCE", "STALE_CURSOR"} or (code.startswith("AMBIGUOUS") and code != "AMBIGUOUS_TIME"):
            self.exit_code = 4
        elif code.startswith(("INVALID", "UNSUPPORTED")) or code in {"IDEMPOTENCY_CONFLICT", "MISSING_ARGUMENT", "CONFIRMATION_REQUIRED", "VALIDATION_ERROR", "AMBIGUOUS_TIME"}:
            self.exit_code = 2
        else:
            self.exit_code = 1


def utc_now():
    return dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def envelope(data=None, error=None, tool="apple-desk"):
    return {"schemaVersion": SCHEMA_VERSION, "ok": error is None,
            "data": data, "error": error,
            "meta": {"observedAt": utc_now(), "version": VERSION, "tool": tool}}


def emit_success(data, tool="apple-desk"):
    print(json.dumps(envelope(data, tool=tool), ensure_ascii=False, allow_nan=False))
    return 0


def emit_error(error, tool="apple-desk"):
    if not isinstance(error, ToolError):
        error = ToolError("INTERNAL_ERROR", str(error))
    print(json.dumps(envelope(error.data, {"code": error.code, "message": error.message,
                      "details": error.details}, tool=tool), ensure_ascii=False, allow_nan=False))
    return error.exit_code


class StateStore:
    """Atomic JSON state with a process lock and durable uncertain-write journal."""
    def __init__(self, directory=None):
        self.directory = Path(directory or os.environ.get("APPLE_DESK_STATE_DIR") or
                              Path.home() / "Library/Application Support/Apple Desk").expanduser().absolute()
        if self.directory in {Path("/"), Path.home(), Path("/tmp"), Path("/private/tmp")}:
            raise ToolError("INVALID_STATE_DIRECTORY", "Choose a dedicated private state directory.")
        self._lock_fd = None

    def _prepare(self):
        self.directory.mkdir(parents=True, mode=0o700, exist_ok=True)
        info = self.directory.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ToolError("INVALID_STATE_DIRECTORY", "State directory must be an owned, real directory.")
        self.directory.chmod(0o700)

    def _path(self, relative):
        relative = Path(relative)
        if relative.is_absolute() or not relative.parts or any(p in {"..", "."} for p in relative.parts):
            raise ToolError("INVALID_STATE_PATH", "State paths must be relative and cannot traverse directories.")
        path = self.directory / relative
        current = self.directory
        for component in relative.parts:
            current = current / component
            if current.is_symlink():
                raise ToolError("INVALID_STATE_PATH", "State paths cannot contain symlinks.")
        return path

    @contextlib.contextmanager
    def locked(self):
        if self._lock_fd is not None:
            yield self
            return
        self._prepare()
        fd = os.open(self.directory / ".lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ToolError("BUSY", "Another Apple Desk state operation is running; try again later.")
            self._lock_fd = fd
            yield self
        finally:
            self._lock_fd = None
            os.close(fd)

    def read(self, relative, default=None):
        path = self._path(relative)
        try:
            with path.open(encoding="utf-8") as stream:
                return json.load(stream)
        except FileNotFoundError:
            return default
        except (ValueError, OSError) as exc:
            raise ToolError("STATE_ERROR", "Cannot read local state.", {"path": str(path), "reason": str(exc)})

    def write(self, relative, obj):
        self._prepare()
        path = self._path(relative)
        path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        self._path(relative)
        raw = json.dumps(obj, ensure_ascii=False, allow_nan=False).encode("utf-8")
        fd, temp = tempfile.mkstemp(prefix=".write-", dir=path.parent)
        try:
            with os.fdopen(fd, "wb") as stream:
                os.fchmod(stream.fileno(), 0o600)
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp, path)
            dirfd = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(dirfd)
            finally:
                os.close(dirfd)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    @staticmethod
    def operation_path(key):
        if not isinstance(key, str) or not key.strip() or len(key) > 256:
            raise ToolError("INVALID_IDEMPOTENCY_KEY", "Use a nonempty idempotency key of at most 256 characters.")
        return "operations/" + hashlib.sha256(key.encode()).hexdigest() + ".json"

    def operation(self, key):
        result = self.read(self.operation_path(key))
        if result is None:
            raise ToolError("NOT_FOUND", "No operation exists for that key.")
        return result

    def perform(self, key, kind, payload, operation, preflight=None):
        path = self.operation_path(key)
        digest = hashlib.sha256(json.dumps({"kind": kind, "payload": payload}, sort_keys=True,
                                           ensure_ascii=False, allow_nan=False).encode()).hexdigest()
        with self.locked():
            old = self.read(path)
            if old:
                if old.get("digest") != digest:
                    raise ToolError("IDEMPOTENCY_CONFLICT", "This key was used with a different operation or payload.")
                if old.get("status") == "complete":
                    return dict(old["result"], operationKey=key, replayed=True)
                raise ToolError("OPERATION_STATUS_UNKNOWN", "The earlier write may have completed. Inspect it before taking further action; this key will not execute again.",
                                {"operationKey": key, "kind": kind, "writeMayHaveTakenEffect": True})
            if preflight is not None:
                preflight()
            record = {"operationKey": key, "kind": kind, "digest": digest,
                      "status": "pending", "startedAt": utc_now()}
            self.write(path, record)
            try:
                result = operation()
                if not isinstance(result, dict):
                    result = {"result": result}
                record.update(status="complete", finishedAt=utc_now(), result=result)
                self.write(path, record)
            except Exception as exc:
                record.update(status="unknown", finishedAt=utc_now(),
                              error={"code": getattr(exc, "code", "INTERNAL_ERROR"), "message": str(exc)})
                try:
                    self.write(path, record)
                except Exception:
                    pass  # Durable pending record is equally conservative.
                raise ToolError("OPERATION_STATUS_UNKNOWN", "The write may have completed. Inspect its result before any further action; this key will not execute again.",
                                {"operationKey": key, "kind": kind, "writeMayHaveTakenEffect": True,
                                 "cause": record["error"]}, getattr(exc, "data", None)) from exc
            return dict(result, operationKey=key, replayed=False)
