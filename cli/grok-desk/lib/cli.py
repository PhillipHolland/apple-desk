#!/usr/bin/env python3
"""grok-desk 0.1.7 — onboard a Mac and build local search indexes.

Caches stay under ~/.cache (0700 dirs, 0600 databases). Nothing is uploaded.
No Keychain. No Passwords. Mail is not called. Calendar and Reminders are
called only by reindex, once each, and only through their CLIs.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

import common
import contacts_index
import messages_index
import calendar_index
import reminders_index

VERSION = common.VERSION
SAFE_DOCTORS = (
    "grok-notes",
    "grok-contacts",
    "grok-messages",
    "grok-shortcuts",
    "grok-icloud",
    "grok-spotlight",
    "grok-focus",
    "grok-safari",
)
SURFACES = ("notes", "messages", "contacts", "calendar", "reminders")

GAPS = [
    "Indexes are local SQLite files under ~/.cache. grok-desk never uploads them and never copies chat.db.",
    "Notes uses the existing grok-notes cache (~/.cache/grok-notes/index.sqlite). There is no second notes database.",
    "Messages stores chat guid, display name, group flag, service, last date, and message count, plus an FTS index of message text when Full Disk Access allows the read. Send rules are unchanged: grok-messages --to is 1:1 only; groups need --chat-guid.",
    "The contacts cache (id, name, org, phones, emails) is off unless onboard --index-contacts or reindex --only contacts. It is not built by a normal onboard.",
    "Calendar reindex runs grok-calendar doctor once. When that is authorized it stores calendar names and events in a portable window: past 30 days through the next 90 days (override with --past-days/--future-days or GROK_CALENDAR_PAST_DAYS and GROK_CALENDAR_FUTURE_DAYS, each 0..366). One calendar index at a time (uid, title, start, end, all-day, calendar name). Only the Apple system calendar titled Scheduled Reminders is skipped by name. A wide window that times out is read in 14-day slices, and each slice is retried once. A slice over 800 events is split further by date. Doctor timeout or denied Automation sets pending_allow and is not retried. Locations and notes are not stored. grok-calendar list/search and grok-desk search read this cache first.",
    "Reminders reindex runs a names-only doctor, lean lists, then one incomplete-only collect (id, list, title, due). Notes are not stored. Timeout or denied Automation sets pending_allow and is not retried. Mail is not indexed. Focus and Safari are probed by doctor and are not part of this index.",
    "Keychain, Passwords, and HomeKit are out on purpose.",
    "An optional one-line signature lives in ~/.config/grok-desk/signature. grok-desk does not send messages and does not append that line.",
]


def die(code: int, error: str, message: str, as_json: bool) -> None:
    payload = {"ok": False, "tool": common.TOOL, "version": VERSION, "error": error, "message": message}
    if as_json:
        print(json.dumps(payload))
    else:
        print(f"{error}: {message}", file=sys.stderr)
    raise SystemExit(code)


def emit(data: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data))
        return
    print(f"grok-desk {data.get('version', VERSION)}")
    if data.get("error"):
        print(f"{data['error']}: {data.get('message', '')}")
    for tool in data.get("tools") or []:
        mark = "yes" if tool.get("present") else "no"
        print(f"  {tool['name']}: {mark}  {tool.get('version') or ''}")
    for doc in data.get("doctors") or []:
        checked = doc.get("checked") or "-"
        if doc.get("present") is False:
            mark = "missing"
        elif checked == "doctor":
            mark = "ok" if doc.get("ok") else (doc.get("error") or "fail")
        elif checked == "version":
            mark = "version"
        else:
            mark = checked
        print(f"  doctor {doc.get('name')}: {mark}  {doc.get('version') or ''}")
    for cache in data.get("caches") or []:
        print(
            f"  cache {cache['name']}: exists={cache.get('exists')} bytes={cache.get('bytes', 0)} {cache.get('path', '')}"
        )
    for row in data.get("indexes") or []:
        bits = [f"{k}={v}" for k, v in row.items() if k not in ("message", "detail") and not isinstance(v, (dict, list))]
        print("  " + " ".join(bits))
    for line in data.get("gaps") or []:
        print(f"- {line}")
    if "summary" in data and isinstance(data["summary"], list):
        for row in data["summary"]:
            print(
                f"  {row.get('name')}: rows={row.get('rows')} status={row.get('status')} "
                f"bytes={row.get('bytes')} indexed={row.get('indexedAt')}"
            )
    sig = data.get("signature")
    if isinstance(sig, dict) and "signature" not in sig:
        print("  signature: " + ("set" if sig.get("set") else "unset"))
    elif isinstance(sig, dict) and sig.get("set") and sig.get("signature"):
        print(sig["signature"])
    elif isinstance(sig, dict):
        print("signature: unset")


def probe_tools() -> list[dict]:
    tools = []
    for name in common.TOOLS:
        path = common.which(name)
        short = name.removeprefix("grok-")
        entry = {"name": short, "bin": name, "present": bool(path), "path": path}
        if path:
            entry["version"] = common.version_of(path)
            entry["versionOnly"] = name in common.VERSION_ONLY
        tools.append(entry)
    return tools


def probe_caches() -> list[dict]:
    home_cache = Path.home() / ".cache"
    names = list(common.CACHE_NAMES)
    if home_cache.exists():
        for child in sorted(home_cache.glob("grok-*")):
            if child.is_dir() and child.name not in names:
                names.append(child.name)
    out = []
    for name in names:
        folder = common.cache_dir(name)
        db = folder / "index.sqlite"
        out.append(
            {
                "name": name.removeprefix("grok-"),
                "path": str(folder),
                "exists": folder.exists(),
                "db": str(db) if db.exists() else None,
                "bytes": common.dir_bytes(folder),
            }
        )
    return out


def _meta(con: sqlite3.Connection) -> dict:
    try:
        return {row[0]: row[1] for row in con.execute("SELECT key, value FROM meta")}
    except sqlite3.OperationalError:
        return {}


def _count(con: sqlite3.Connection, table: str) -> int | None:
    try:
        return int(con.execute(f"SELECT count(*) FROM {table}").fetchone()[0])
    except sqlite3.OperationalError:
        return None


def status_rows() -> list[dict]:
    specs = [
        ("notes", "notes", "indexed_at"),
        ("messages", "chats", "indexed_at"),
        ("contacts", "contacts", "indexed_at"),
        ("calendar", "events", "indexed_at"),
        ("reminders", "reminders", "indexed_at"),
    ]
    rows = []
    for name, table, when_key in specs:
        folder = common.cache_dir(f"grok-{name}")
        path = common.db_path(f"grok-{name}")
        row = {
            "name": name,
            "path": str(path),
            "exists": path.exists(),
            "bytes": common.dir_bytes(folder),
            "rows": 0,
            "indexedAt": None,
            "status": "missing",
        }
        if not path.exists():
            if name == "contacts":
                row["status"] = "off"
            elif name in ("calendar", "reminders"):
                row["status"] = "not_stubbed"
            rows.append(row)
            continue
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            meta = _meta(con)
            count = _count(con, table)
            row["rows"] = 0 if count is None else count
            row["indexedAt"] = meta.get(when_key)
            row["status"] = meta.get("status") or ("ok" if count is not None else "unreadable")
            if name == "messages":
                row["ftsRows"] = _count(con, "message_fts")
                row["mode"] = meta.get("mode")
            if name == "notes":
                row["folders"] = _count(con, "folders")
                row["mode"] = meta.get("mode")
            if name == "calendar":
                row["calendars"] = _count(con, "calendars")
                row["windowFrom"] = meta.get("window_from")
                row["windowTo"] = meta.get("window_to")
                row["pastDays"] = meta.get("past_days")
                row["futureDays"] = meta.get("future_days")
            if name == "reminders":
                row["lists"] = _count(con, "lists")
            if name == "contacts" and meta.get("opt_in") != "1":
                row["status"] = meta.get("status") or "present"
        finally:
            con.close()
        rows.append(row)
    return rows


def reindex_notes(full: bool) -> dict:
    path = common.which("grok-notes")
    if not path:
        return {"ok": False, "surface": "notes", "error": "missing_cli", "message": "grok-notes is not on PATH."}
    cmd = [path, "reindex", "--json"]
    if full:
        cmd.append("--full")
    result = common.run_cmd(cmd, 180)
    if result.get("error") == "timeout":
        return {
            "ok": False,
            "surface": "notes",
            "error": "timeout",
            "message": "grok-notes reindex exceeded 180s. Not retried.",
        }
    summary = {"ok": result.get("ok"), "surface": "notes", "code": result.get("code")}
    raw = result.get("stdout") or ""
    try:
        data = json.loads(raw) if raw.startswith("{") else {}
    except json.JSONDecodeError:
        data = {}
    for key in ("ok", "mode", "notes", "folders", "added", "unchanged", "removed", "bodiesRefreshed", "seconds", "path", "error", "message"):
        if key in data:
            summary[key] = data[key]
    if not data:
        summary["ok"] = False
        summary["error"] = summary.get("error") or "notes_reindex_failed"
        summary["message"] = (result.get("stderr") or "grok-notes reindex did not return JSON.")[:200]
    summary["delegated"] = True
    return summary


def reindex_surface(name: str, full: bool, index_contacts: bool, past_days: int | None = None, future_days: int | None = None) -> dict:
    if name == "notes":
        return reindex_notes(full)
    if name == "messages":
        return messages_index.build(full=full)
    if name == "contacts":
        if not index_contacts:
            return {
                "ok": True,
                "surface": "contacts",
                "status": "skipped",
                "message": "Contacts index is off unless --index-contacts or --only contacts.",
            }
        return contacts_index.build()
    if name == "calendar":
        return calendar_index.build(past_days=past_days, future_days=future_days)
    if name == "reminders":
        return reminders_index.build()
    return {"ok": False, "surface": name, "error": "unknown_surface"}


def do_reindex(full: bool, only: str | None, index_contacts: bool, past_days: int | None = None, future_days: int | None = None) -> dict:
    if only:
        names = [only]
        if only == "contacts":
            index_contacts = True
    else:
        names = ["notes", "messages", "calendar", "reminders"]
        if index_contacts:
            names.append("contacts")
    indexes = [reindex_surface(name, full, index_contacts, past_days, future_days) for name in names]
    ok = all(item.get("ok") for item in indexes)
    return {"ok": ok, "tool": common.TOOL, "version": VERSION, "indexes": indexes}


def safe_doctors() -> list[dict]:
    results = []
    for name in common.TOOLS:
        path = common.which(name)
        short = name.removeprefix("grok-")
        if not path:
            results.append({"name": short, "present": False, "checked": "missing"})
            continue
        version = common.version_of(path)
        if name in common.VERSION_ONLY or name not in SAFE_DOCTORS:
            results.append({"name": short, "present": True, "checked": "version", "version": version})
            continue
        doctor = common.run_cmd([path, "doctor", "--json"], 5)
        entry = {"name": short, "present": True, "checked": "doctor", "version": version, "ok": doctor.get("ok")}
        if doctor.get("error") == "timeout":
            entry["ok"] = False
            entry["error"] = "timeout"
            entry["message"] = "doctor exceeded 5s and was not retried"
        elif doctor.get("stdout", "").startswith("{"):
            try:
                data = json.loads(doctor["stdout"])
            except json.JSONDecodeError:
                data = {}
            entry["ok"] = bool(data.get("ok", doctor.get("ok")))
            if data.get("error"):
                entry["error"] = data.get("error")
            if data.get("code"):
                entry["code"] = data.get("code")
        elif not doctor.get("ok"):
            entry["error"] = "doctor_failed"
            entry["code"] = doctor.get("code")
        results.append(entry)
    return results


def unified_status_doctors() -> list[dict]:
    """Lean probes for `grok-desk status`. No prompts. Bounded timeouts.

    SAFE_DOCTORS run at 5s. Calendar and Reminders use their own lean doctors at 8s
    (count-only; not a full event walk). Mail stays version-only — Mail.app doctor can hang.
    """
    results = safe_doctors()
    by_name = {row.get("name"): row for row in results}
    # Upgrade calendar/reminders from version-only to lean doctor when the CLI exists.
    for name, timeout in (("grok-calendar", 8), ("grok-reminders", 8)):
        short = name.removeprefix("grok-")
        path = common.which(name)
        if not path:
            by_name[short] = {"name": short, "present": False, "checked": "missing"}
            continue
        version = common.version_of(path)
        doctor = common.run_cmd([path, "doctor", "--json"], timeout)
        entry = {"name": short, "present": True, "checked": "doctor", "version": version, "ok": doctor.get("ok")}
        if doctor.get("error") == "timeout":
            entry["ok"] = False
            entry["error"] = "timeout"
            entry["message"] = f"doctor exceeded {timeout}s and was not retried"
        elif (doctor.get("stdout") or "").startswith("{"):
            try:
                data = json.loads(doctor["stdout"])
            except json.JSONDecodeError:
                data = {}
            entry["ok"] = bool(data.get("ok", doctor.get("ok")))
            if data.get("error"):
                entry["error"] = data.get("error")
            if data.get("code"):
                entry["code"] = data.get("code")
            # Portable counts only — never dump event/reminder titles here.
            for key in ("calendars", "lists", "appVersion", "version"):
                if key in data and key not in entry:
                    entry[key] = data[key]
        elif not doctor.get("ok"):
            entry["error"] = "doctor_failed"
            entry["code"] = doctor.get("code")
        by_name[short] = entry
    # Stable order matching common.TOOLS
    ordered = []
    for name in common.TOOLS:
        short = name.removeprefix("grok-")
        if short in by_name:
            ordered.append(by_name.pop(short))
    ordered.extend(by_name.values())
    return ordered



# System Settings paths printed on guided-onboard failure (generic; no machine names).
SETTINGS_FDA = (
    "System Settings → Privacy & Security → Full Disk Access → enable Grok Bot and "
    "Grok Bot Helper, then quit and reopen Grok Bot."
)
SETTINGS_AUTOMATION = (
    "System Settings → Privacy & Security → Automation → Grok Bot (and Grok Bot Helper) → {app}."
)
SETTINGS_CALENDARS = (
    "System Settings → Privacy & Security → Calendars → enable Grok Bot and Grok Bot Helper, "
    "then quit and reopen Grok Bot."
)


def _parse_doctor_stdout(raw: str) -> dict:
    raw = (raw or "").strip()
    if not raw.startswith("{"):
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _run_surface_doctor(bin_name: str, timeout: float, extra_args: list[str] | None = None) -> dict:
    """One doctor attempt. Never retries. Returns a gate-shaped dict."""
    path = common.which(bin_name)
    short = bin_name.removeprefix("grok-")
    if not path:
        return {
            "id": short,
            "name": short,
            "bin": bin_name,
            "ok": False,
            "present": False,
            "error": "missing_cli",
            "exitCode": 2,
            "message": f"{bin_name} is not on PATH. Finish Install (docs/INSTALL.md), then re-run.",
            "settingsPath": None,
        }
    cmd = [path, "doctor", "--json"] + (extra_args or [])
    result = common.run_cmd(cmd, timeout, stdout_limit=16000)
    version = common.version_of(path)
    data = _parse_doctor_stdout(result.get("stdout") or "")
    code = int(result.get("code") or (0 if result.get("ok") else 1))
    if result.get("error") == "timeout":
        return {
            "id": short,
            "name": short,
            "bin": bin_name,
            "ok": False,
            "present": True,
            "version": version,
            "error": "timeout",
            "exitCode": 4,
            "message": f"{bin_name} doctor exceeded {timeout}s (hang or dialog). Do not retry while AFK.",
            "settingsPath": SETTINGS_AUTOMATION.format(app=short.title()),
            "doctor": data,
        }
    err = data.get("error") or result.get("error")
    ok = bool(data.get("ok", result.get("ok")))
    settings = None
    message = data.get("message") or data.get("historyMessage") or ""
    # Normalize TCC-style failures into Settings paths.
    blob = " ".join(
        str(x) for x in (err, message, data.get("automation"), json.dumps(data.get("history") or {})) if x
    )
    if code == 5 or err == "needs_full_disk_access" or "needs_full_disk_access" in blob:
        ok = False
        code = 5
        err = "needs_full_disk_access"
        settings = SETTINGS_FDA
        message = message or "Messages history needs Full Disk Access. Send does not."
    elif code == 3 or err in {"automation_denied", "accessibility_denied", "calendar_tcc"} or "-1743" in blob:
        ok = False
        code = 3
        err = err or "automation_denied"
        if err == "calendar_tcc" or "calendar_tcc" in blob:
            settings = SETTINGS_CALENDARS
        else:
            app = "Calendar" if short == "calendar" else short.title()
            if short == "messages":
                app = "Messages"
            elif short == "contacts":
                app = "Contacts"
            settings = SETTINGS_AUTOMATION.format(app=app)
        message = message or "Not authorized to send Apple events (-1743). Stop. Do not loop."
    elif code == 4 or err in {"automation_timeout", "timeout"} or "-1712" in blob:
        ok = False
        code = 4
        err = err or "automation_timeout"
        settings = SETTINGS_AUTOMATION.format(app=short.title() if short != "messages" else "Messages")
        message = message or "Timed out (-1712). Hang or dialog still up. Do not loop while AFK."
    return {
        "id": short,
        "name": short,
        "bin": bin_name,
        "ok": ok,
        "present": True,
        "version": version,
        "error": None if ok else (err or "doctor_failed"),
        "exitCode": 0 if ok else code,
        "message": message or None,
        "settingsPath": None if ok else settings,
        "doctor": data,
        "automation": data.get("automation"),
        "historyAvailable": (data.get("history") or {}).get("available") if isinstance(data.get("history"), dict) else data.get("history"),
    }


def do_guided_onboard(index_contacts: bool, skip_optional: bool = False, skip_signature: bool = False) -> tuple[dict, int]:
    """Walk permission gates one-by-one. Stop at first hard failure.

    Returns (payload, process_exit_code). Re-run after the user clicks Allow.
    """
    links = [common.link_if_needed(name) for name in ("grok-desk",) + common.TOOLS]
    gates: list[dict] = []
    stopped = None

    def fail(gate: dict) -> tuple[dict, int]:
        nonlocal stopped
        stopped = gate
        gates.append(gate)
        code = int(gate.get("exitCode") or 1)
        payload = {
            "ok": False,
            "tool": common.TOOL,
            "version": VERSION,
            "mode": "guided",
            "links": links,
            "gates": gates,
            "stoppedAt": gate.get("id"),
            "nextSettingsPath": gate.get("settingsPath"),
            "message": gate.get("message"),
            "hint": "Fix the Settings path above, then re-run: grok-desk onboard --guided",
        }
        return payload, code

    # 1) Messages history — Full Disk Access
    msg = _run_surface_doctor("grok-messages", 8)
    hist = msg.get("doctor") or {}
    history = hist.get("history") if isinstance(hist.get("history"), dict) else {}
    hist_flag = history.get("available")
    if hist_flag is None:
        hist_flag = msg.get("historyAvailable")
    # Explicit false / exit 5 => FDA fail. True or ok doctor without FDA error => pass.
    hist_denied = (
        msg.get("error") == "needs_full_disk_access"
        or msg.get("exitCode") == 5
        or hist_flag is False
    )
    hist_ok = (not hist_denied) and (hist_flag is True or (msg.get("ok") and hist_flag is not False))
    if msg.get("error") == "needs_full_disk_access" or (hist_denied and not hist_ok):
        gate = dict(msg)
        gate.update({
            "id": "messages-fda",
            "title": "Full Disk Access (Messages history)",
            "why": "Read chat.db for history, unread, and search. Send does not need Full Disk Access.",
            "ok": False,
            "error": "needs_full_disk_access",
            "exitCode": 5,
            "settingsPath": SETTINGS_FDA,
            "message": gate.get("message") or "Messages history needs Full Disk Access.",
        })
        return fail(gate)
    if msg.get("exitCode") in (3, 4) and not msg.get("ok"):
        # Hard automation failure before we can trust history — still report as messages gate.
        gate = dict(msg)
        gate["id"] = "messages-automation"
        gate["title"] = "Automation → Messages"
        gate["why"] = "Send and the Messages scripting chat list."
        gate["settingsPath"] = gate.get("settingsPath") or SETTINGS_AUTOMATION.format(app="Messages")
        return fail(gate)
    gates.append({
        "id": "messages-fda",
        "title": "Full Disk Access (Messages history)",
        "ok": True,
        "version": msg.get("version"),
        "why": "Read chat.db for history, unread, and search.",
    })

    # 2) Messages Automation
    auto = (msg.get("automation") or (msg.get("doctor") or {}).get("automation") or "")
    if not msg.get("ok") or str(auto).lower() not in {"authorized", "ok", "allowed", ""}:
        # empty automation with ok=true still counts as pass (older CLIs)
        if not msg.get("ok") or str(auto).lower() in {"denied", "unauthorized", "not_authorized"}:
            gate = dict(msg)
            gate.update({
                "id": "messages-automation",
                "title": "Automation → Messages",
                "why": "Send and the Messages scripting chat list.",
                "ok": False,
                "exitCode": msg.get("exitCode") or 3,
                "settingsPath": SETTINGS_AUTOMATION.format(app="Messages"),
                "message": msg.get("message") or "Messages Automation not authorized.",
            })
            return fail(gate)
    if not msg.get("ok"):
        gate = dict(msg)
        gate.update({
            "id": "messages-automation",
            "title": "Automation → Messages",
            "why": "Send and the Messages scripting chat list.",
            "settingsPath": msg.get("settingsPath") or SETTINGS_AUTOMATION.format(app="Messages"),
        })
        return fail(gate)
    gates.append({
        "id": "messages-automation",
        "title": "Automation → Messages",
        "ok": True,
        "version": msg.get("version"),
        "automation": auto or "authorized",
    })

    # 3–7 required app gates
    required = [
        ("notes", "grok-notes", 8, None, "Notes", "Notes.app folders and note bodies."),
        ("contacts", "grok-contacts", 12, ["--live"], "Contacts", "Live Contacts.app (cache-only doctor is not this gate)."),
        ("calendar", "grok-calendar", 10, None, "Calendar", "Calendar.app lean doctor (count-only)."),
        ("reminders", "grok-reminders", 10, None, "Reminders", "Reminders.app lean doctor (names-only)."),
        ("shortcuts", "grok-shortcuts", 8, None, "Shortcuts", "List shortcuts via /usr/bin/shortcuts."),
    ]
    for gid, bin_name, timeout, extra, app, why in required:
        row = _run_surface_doctor(bin_name, timeout, extra)
        row["id"] = gid
        row["title"] = f"Automation → {app}" if gid != "shortcuts" else "Shortcuts"
        row["why"] = why
        if not row.get("ok"):
            if not row.get("settingsPath"):
                if row.get("error") == "calendar_tcc":
                    row["settingsPath"] = SETTINGS_CALENDARS
                elif gid == "shortcuts":
                    row["settingsPath"] = None
                    row["message"] = row.get("message") or "Shortcuts CLI failed. Finish Install, then re-run."
                else:
                    row["settingsPath"] = SETTINGS_AUTOMATION.format(app=app)
            # Calendar: Automation ok but TCC for calendars data
            doc = row.get("doctor") or {}
            if gid == "calendar" and (doc.get("error") == "calendar_tcc" or row.get("error") == "calendar_tcc"):
                row["settingsPath"] = SETTINGS_CALENDARS
            return fail(row)
        gates.append({"id": gid, "title": row["title"], "ok": True, "version": row.get("version"), "why": why})

    # 8–9 optional
    optional = [
        ("mail", "grok-mail", 5, "Mail", True),
        ("icloud", "grok-icloud", 8, "iCloud Drive", False),
    ]
    for gid, bin_name, timeout, label, version_only in optional:
        if skip_optional:
            gates.append({"id": gid, "title": label, "ok": True, "optional": True, "skipped": True})
            continue
        path = common.which(bin_name)
        if not path:
            gates.append({
                "id": gid,
                "title": label,
                "ok": True,
                "optional": True,
                "present": False,
                "message": f"{bin_name} not installed yet (optional).",
            })
            continue
        if version_only or bin_name in common.VERSION_ONLY:
            ver = common.version_of(path)
            gates.append({
                "id": gid,
                "title": label,
                "ok": True,
                "optional": True,
                "checked": "version",
                "version": ver,
                "message": "Optional. Prefer a cloud mail connector when possible. Automation → Mail if you use Mail.app.",
                "settingsPath": SETTINGS_AUTOMATION.format(app="Mail"),
            })
            continue
        row = _run_surface_doctor(bin_name, timeout)
        row["id"] = gid
        row["title"] = label
        row["optional"] = True
        if not row.get("ok"):
            # Optional: record and continue (do not stop), unless hard -1743 and user cares — still continue.
            row["continued"] = True
            row["message"] = (row.get("message") or "Optional gate failed.") + " Continuing. Do not loop."
            if not row.get("settingsPath") and gid == "mail":
                row["settingsPath"] = SETTINGS_AUTOMATION.format(app="Mail")
        gates.append(row)

    # 10) Signature — ask, never bake a default line
    line = common.read_signature()
    if line is None and not skip_signature:
        gate = {
            "id": "signature",
            "title": "Outgoing signature",
            "ok": False,
            "error": "needs_signature",
            "exitCode": 2,
            "settingsPath": None,
            "why": "Optional footer for drafts the bot shows before send. The send CLI does not append it.",
            "message": (
                "No signature stored. Ask the user how outgoing messages should be signed "
                "(or none). Then run: grok-desk signature --set YOUR_LINE. "
                "If they want none: grok-desk onboard --guided --skip-signature"
            ),
            "nextCommand": "grok-desk signature --set YOUR_LINE  # or onboard --guided --skip-signature",
        }
        return fail(gate)
    gates.append({
        "id": "signature",
        "title": "Outgoing signature",
        "ok": True,
        "set": bool(line),
        "skipped": bool(line is None and skip_signature),
        "message": None if line else "Signature left unset (--skip-signature).",
    })

    # 11) Reindex once
    indexed = do_reindex(False, None, index_contacts)
    gate = {
        "id": "reindex",
        "title": "Local reindex",
        "ok": bool(indexed.get("ok")),
        "indexes": indexed.get("indexes"),
    }
    if not gate["ok"]:
        # pending_allow on a surface — point at Automation, do not loop
        gate["error"] = "reindex_incomplete"
        gate["exitCode"] = 1
        gate["message"] = "Reindex did not fully succeed. Fix pending_allow Automation, then: grok-desk reindex"
        gate["settingsPath"] = SETTINGS_AUTOMATION.format(app="Calendar / Reminders / Notes")
        return fail(gate)
    gates.append(gate)

    payload = {
        "ok": True,
        "tool": common.TOOL,
        "version": VERSION,
        "mode": "guided",
        "links": links,
        "gates": gates,
        "indexes": indexed.get("indexes"),
        "signatureSet": bool(line),
        "message": "Guided onboard complete.",
    }
    return payload, 0


def emit_guided(data: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps(data))
        return
    print(f"grok-desk {data.get('version', VERSION)} guided onboard")
    if data.get("stoppedAt"):
        print(f"stoppedAt: {data['stoppedAt']}")
    if data.get("nextSettingsPath"):
        print(f"nextSettingsPath: {data['nextSettingsPath']}")
    if data.get("message"):
        print(data["message"])
    if data.get("hint"):
        print(data["hint"])
    for gate in data.get("gates") or []:
        mark = "ok" if gate.get("ok") else ("skip" if gate.get("skipped") else "FAIL")
        title = gate.get("title") or gate.get("id")
        extra = gate.get("version") or gate.get("error") or ""
        print(f"  [{mark}] {title}  {extra}".rstrip())
        if not gate.get("ok") and gate.get("settingsPath"):
            print(f"       → {gate['settingsPath']}")

def do_onboard(full: bool, index_contacts: bool) -> dict:
    links = [common.link_if_needed(name) for name in ("grok-desk",) + common.TOOLS]
    doctors = safe_doctors()
    indexed = do_reindex(full, None, index_contacts)
    ok = indexed["ok"]
    return {
        "ok": ok,
        "tool": common.TOOL,
        "version": VERSION,
        "links": links,
        "doctors": doctors,
        "indexes": indexed["indexes"],
    }



def _fts_query(text: str) -> str:
    """Quoted AND of alphanumeric tokens. Empty when nothing is searchable."""
    parts = []
    token = []
    for ch in text:
        if ch.isalnum():
            token.append(ch)
        else:
            if len(token) >= 2:
                parts.append('"' + "".join(token) + '"')
            token = []
    if len(token) >= 2:
        parts.append('"' + "".join(token) + '"')
    return " AND ".join(parts[:8])


def do_search(surface: str, query: str, limit: int) -> dict:
    """Query a local index when present. No Apple Events."""
    import sqlite3
    q = (query or "").strip()
    if len(q) < 2:
        return {"ok": False, "error": "missing_query", "message": "Search needs at least 2 characters."}
    path = common.db_path(f"grok-{surface}")
    if not path.exists():
        return {"ok": False, "error": "no_index", "message": f"No {surface} index. Run: grok-desk reindex --only {surface}"}
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        meta = _meta(con)
        if meta.get("status") == "pending_allow":
            return {"ok": False, "error": "pending_allow", "message": f"{surface} index is pending_allow. Fix Automation, then reindex."}
        needle = f"%{q}%"
        rows = []
        if surface == "calendar":
            for uid, cal, title, start_at, end_at, all_day in con.execute(
                "SELECT uid, calendar, title, start_at, end_at, all_day FROM events "
                "WHERE title LIKE ? COLLATE NOCASE ORDER BY start_at LIMIT ?",
                (needle, limit),
            ):
                rows.append({"uid": uid, "calendar": cal, "title": title, "start": start_at, "end": end_at, "allDay": bool(all_day)})
        elif surface == "reminders":
            for ident, lst, title, due, completed in con.execute(
                "SELECT id, list_name, title, due, completed FROM reminders "
                "WHERE title LIKE ? COLLATE NOCASE ORDER BY due IS NULL, due LIMIT ?",
                (needle, limit),
            ):
                rows.append({"id": ident, "list": lst, "title": title, "due": due or None, "completed": bool(completed)})
        elif surface == "contacts":
            for ident, name, org in con.execute(
                "SELECT id, name, org FROM contacts WHERE name LIKE ? COLLATE NOCASE OR org LIKE ? COLLATE NOCASE LIMIT ?",
                (needle, needle, limit),
            ):
                rows.append({"id": ident, "name": name, "org": org})
        elif surface == "notes":
            try:
                fts = _fts_query(q)
                seen = set()
                if fts:
                    for row in con.execute(
                        "SELECT id, title, folder FROM notes WHERE rowid IN ("
                        "SELECT rowid FROM notes_fts WHERE notes_fts MATCH ?) LIMIT ?",
                        (fts, limit),
                    ):
                        seen.add(row[0])
                        rows.append({"id": row[0], "title": row[1], "folder": row[2]})
                if len(rows) < limit:
                    for row in con.execute(
                        "SELECT id, title, folder FROM notes WHERE title LIKE ? COLLATE NOCASE LIMIT ?",
                        (needle, limit),
                    ):
                        if row[0] in seen:
                            continue
                        rows.append({"id": row[0], "title": row[1], "folder": row[2]})
                        if len(rows) >= limit:
                            break
            except sqlite3.OperationalError as exc:
                return {"ok": False, "error": "schema", "message": str(exc)[:200]}
        elif surface == "messages":
            try:
                seen = set()
                for row in con.execute(
                    "SELECT guid, display_name, last_message_date FROM chats "
                    "WHERE display_name LIKE ? COLLATE NOCASE LIMIT ?",
                    (needle, limit),
                ):
                    seen.add(row[0])
                    rows.append({"chatGuid": row[0], "name": row[1], "lastDate": row[2]})
                fts = _fts_query(q)
                if fts and len(rows) < limit:
                    for row in con.execute(
                        "SELECT DISTINCT chat_guid FROM message_fts WHERE message_fts MATCH ? LIMIT ?",
                        (fts, limit),
                    ):
                        guid = row[0]
                        if not guid or guid in seen:
                            continue
                        chat = con.execute(
                            "SELECT display_name, last_message_date FROM chats WHERE guid = ?",
                            (guid,),
                        ).fetchone()
                        seen.add(guid)
                        rows.append({
                            "chatGuid": guid,
                            "name": None if chat is None else chat[0],
                            "lastDate": None if chat is None else chat[1],
                            "matched": "text",
                        })
                        if len(rows) >= limit:
                            break
            except sqlite3.OperationalError as exc:
                return {"ok": False, "error": "schema", "message": str(exc)[:200]}
        else:
            return {"ok": False, "error": "unknown_surface", "message": surface}
        return {
            "ok": True,
            "tool": common.TOOL,
            "version": VERSION,
            "surface": surface,
            "source": "cache",
            "query": q,
            "count": len(rows),
            "hits": rows,
            "path": str(path),
            "indexedAt": meta.get("indexed_at"),
        }
    finally:
        con.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="grok-desk", description="Local Apple Desk onboarding and indexes.")
    parser.add_argument("--version", action="version", version=f"grok-desk {VERSION}")
    sub = parser.add_subparsers(dest="cmd")

    def add_json(command):
        command.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor", help="Which CLIs and caches exist")
    add_json(doctor)

    onboard = sub.add_parser("onboard", help="Link missing bins, safe checks, then reindex")
    onboard.add_argument("--full", action="store_true")
    onboard.add_argument("--index-contacts", action="store_true", help="Opt in to the contacts phone/email cache")
    onboard.add_argument(
        "--guided",
        action="store_true",
        help="Walk Mac permission gates one-by-one; stop on first failure with System Settings path",
    )
    onboard.add_argument(
        "--skip-signature",
        action="store_true",
        help="With --guided, continue reindex when no signature is stored (user chose none)",
    )
    add_json(onboard)

    reindex = sub.add_parser("reindex", help="Build or update local caches")
    reindex.add_argument("--full", action="store_true")
    reindex.add_argument("--only", choices=SURFACES)
    reindex.add_argument("--index-contacts", action="store_true")
    reindex.add_argument("--past-days", type=int, default=None, help="Calendar window before today (default 30, or GROK_CALENDAR_PAST_DAYS)")
    reindex.add_argument("--future-days", type=int, default=None, help="Calendar window after today (default 90, or GROK_CALENDAR_FUTURE_DAYS)")
    add_json(reindex)

    status = sub.add_parser("status", help="Unified caches + lean doctor probes across CLIs")
    add_json(status)

    gaps = sub.add_parser("gaps", help="What this tool will not do")
    add_json(gaps)

    search = sub.add_parser("search", help="Search a local index (no Apple Events)")
    search.add_argument("surface", choices=SURFACES)
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=20)
    add_json(search)

    signature = sub.add_parser("signature", help="Show or set the one-line outgoing signature")
    signature.add_argument("--set", dest="set_text", default=None, help="Store one line. Does not send anything.")
    signature.add_argument("--clear", action="store_true", help="Remove the stored line")
    add_json(signature)
    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    as_json = bool(getattr(args, "json", False))
    if not args.cmd:
        parser.print_help()
        return 2
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    if args.cmd == "doctor":
        data = {
            "ok": True,
            "tool": common.TOOL,
            "version": VERSION,
            "tools": probe_tools(),
            "caches": probe_caches(),
            "signature": {"set": common.read_signature() is not None, "path": str(common.signature_path())},
        }
        emit(data, as_json)
        return 0
    if args.cmd == "gaps":
        data = {"ok": True, "tool": common.TOOL, "version": VERSION, "gaps": GAPS}
        emit(data, as_json)
        return 0
    if args.cmd == "status":
        # Unified rollup: local caches + lean doctor/version probes (apple-tools-style status).
        # Focus/Safari are doctor-only shell-outs; Passwords/HomeKit stay out.
        doctors = unified_status_doctors()
        summary = status_rows()
        ok = True
        for row in doctors:
            if row.get("present") is False:
                ok = False
            if row.get("checked") == "doctor" and row.get("ok") is False:
                ok = False
        data = {
            "ok": ok,
            "tool": common.TOOL,
            "version": VERSION,
            "summary": summary,
            "doctors": doctors,
            "signatureSet": common.read_signature() is not None,
        }
        emit(data, as_json)
        return 0
    if args.cmd == "reindex":
        data = do_reindex(args.full, args.only, args.index_contacts, getattr(args, "past_days", None), getattr(args, "future_days", None))
        emit(data, as_json)
        return 0 if data["ok"] else 1
    if args.cmd == "onboard":
        if getattr(args, "guided", False):
            data, code = do_guided_onboard(
                args.index_contacts,
                skip_optional=False,
                skip_signature=bool(getattr(args, "skip_signature", False)),
            )
            emit_guided(data, as_json)
            return code
        data = do_onboard(args.full, args.index_contacts)
        emit(data, as_json)
        return 0 if data.get("ok") else 1

    if args.cmd == "search":
        data = do_search(args.surface, args.query, args.limit)
        emit(data, as_json)
        return 0 if data.get("ok") else 1
    if args.cmd == "signature":
        if args.clear and args.set_text is not None:
            die(2, "bad_request", "Pass either --set or --clear, not both.", as_json)
        if args.clear:
            common.clear_signature()
            data = {"ok": True, "tool": common.TOOL, "version": VERSION, "signature": {"set": False, "path": str(common.signature_path())}}
            emit(data, as_json)
            return 0
        if args.set_text is not None:
            try:
                line = common.write_signature(args.set_text)
            except ValueError as exc:
                die(2, "bad_signature", str(exc), as_json)
            data = {
                "ok": True,
                "tool": common.TOOL,
                "version": VERSION,
                "signature": {"set": True, "signature": line, "path": str(common.signature_path())},
            }
            emit(data, as_json)
            return 0
        line = common.read_signature()
        if line is None:
            die(2, "unset", 'No signature stored. Ask the user, then grok-desk signature --set "...".', as_json)
        data = {
            "ok": True,
            "tool": common.TOOL,
            "version": VERSION,
            "signature": {"set": True, "signature": line, "path": str(common.signature_path())},
        }
        emit(data, as_json)
        return 0
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
