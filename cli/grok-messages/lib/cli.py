#!/usr/bin/env python3
"""grok-messages command line. Send via Messages.app. History via chat.db."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import secrets
import shlex
import subprocess
import sys
import time
from pathlib import Path

import db

VERSION = "0.2.12"
LIB = Path(__file__).resolve().parent / "messages.js"
ALLOWLIST = Path.home() / ".config" / "grok-messages" / "allowlist"
MAX_TEXT = 4000
CONFIRM_TTL_SECONDS = 600
CONFIRM_FILENAME = "send-confirm.json"

GAPS = [
    "Messages 26 scripting can list chats (id, name, participants) and send text to an existing chat. It cannot read message history. History comes from ~/Library/Messages/chat.db and needs Full Disk Access for the process that runs this CLI (Grok Bot Helper when an agent runs it).",
    "Send to an existing chat uses the Messages scripting list. A missing 1:1 is the exception: when --to is a phone or email handle and the text is non-empty, send --force --confirm TOKEN sends one message, and that first message is what creates the chat. --force alone does not send. The scripting dictionary cannot make an empty chat. A send without --force is a dry-run: it prints a confirm token and does not send or create a chat. A display name with no 1:1 stays not_found. An existing 1:1 is reused. A group name or group guid is still refused. Unknown-sender and junk chats are often absent, so history can show them while a --chat-guid send returns not_in_messages_ui. Nothing is sent in that case.",
    "send --to is a person only (phone, email, or a 1:1 chat). It never targets a group, even when that handle is a member of one. The send uses Messages' participant object (1:1). If the handle exists only in a group, send does not message that group. A phone or email handle plus text can start a separate 1:1; the group itself still needs --chat-guid. A group name or group guid is refused. This CLI does not create groups.",
    "attachments lists metadata for one chat (name, mime, bytes, sticker, date). Default output has no absolute path. --reveal-path prints the local absolute path already stored on the row and warns that it is a private file. It does not open, copy, upload, or search the disk. A row with no stored path says so and exits cleanly. Send still cannot attach a file. react is a 1:1 wrap of imsg react (love, like, dislike, laugh, emphasis, question; emphasize means emphasis). It is a dry-run unless --force, has no --chat-guid, and refuses groups. --force does not pre-check the screen lock and does not activate Messages. It runs imsg react once. Vendor imsg activates Messages and exits -2700 if it is not in front. It does not call imsg tapback, imsg launch, or IMCore, and it has no AppleScript fallback. Stickers-as-send, message effects, edits, unsends, and replies are still absent. Send is plain text only, capped at 4000 characters.",
    "No pin, mute, hide alerts, or Focus filter changes. mark-read does not write chat.db and does not use IMCore. With --force it makes Messages frontmost, then clicks an enabled Conversation > Mark All as Read. Activate alone is not success. It does not send.",
    "Search looks at the message text column only. Attachment-only rows and a few attributed-body-only rows have null text and will not match. Snippets are capped.",
    "Reactions are labeled (love, like, dislike, laugh, emphasize, question, emoji) from the row itself. The message that was reacted to is not pulled in.",
    "An optional allowlist file (~/.config/grok-messages/allowlist) restricts send targets if it exists. One handle or chat guid per line. If the file exists and has no targets, every send is refused. If the file does not exist, send still needs a confirm token from a dry-run plus --force --confirm. --force alone does not send. The token is stored mode 0600 under ~/.config/grok-messages and does not contain the message body.",
    "There is no cloud iMessage API here. This does not talk to iCloud.com.",
    "imsg history and imsg watch are read-only wraps of the vendored imsg binary ($GROK_MESSAGES_IMSG when executable, else the source checkout release binary). There is no imsg attachments subcommand. Attachment paths are original_path fields on those JSON rows. Default is a dry-run: it prints the argv and does not run imsg, so it prints no message body and no path. --force runs imsg with --json and still omits message text. --reveal-path is the only path print, and it does not open the file. Attachment conversion is never requested, because that writes a cache. send, react, and mark-read do not use this wrap. It does not call imsg send, imsg tapback, imsg launch, or IMCore. imsg search stays on the in-house search command.",
    "unread counts incoming rows with is_read = 0. It does not mark chats read, does not return message text, and does not call Messages.app. Names come from the chat display name, then the local contacts cache when that index exists. Marking read is the separate mark-read command.",
]


def die(code, error, message, as_json):
    if as_json:
        print(json.dumps({
            "ok": False,
            "tool": "grok-messages",
            "version": VERSION,
            "error": error,
            "code": code,
            "message": message,
        }))
    else:
        print(f"grok-messages: {error}", file=sys.stderr)
        if message:
            print(message, file=sys.stderr)
        if error == "automation_denied":
            print("Messages automation was denied. System Settings → Privacy & Security → Automation → Grok Bot (or Grok Bot Helper, or Terminal) → Messages on.", file=sys.stderr)
            print("If a dialog is still on screen, click it once. Do not retry in a loop.", file=sys.stderr)
        if error == "automation_timeout":
            print("Timed out. That is a hang or a dialog still on screen, not proof that access was denied.", file=sys.stderr)
            print("If a dialog is up, answer it once. If none is up, Messages may be busy. Do not retry in a loop.", file=sys.stderr)
        if error == "needs_full_disk_access":
            print("System Settings → Privacy & Security → Full Disk Access → Grok Bot and Grok Bot Helper on.", file=sys.stderr)
            print("Quit and reopen Grok Bot after changing that. Send does not need Full Disk Access.", file=sys.stderr)
        if error == "accessibility_denied":
            print("System Settings → Privacy & Security → Accessibility → allow the app that runs this CLI (Grok Bot Helper, Terminal, or osascript).", file=sys.stderr)
            print("That prompt is one click. Do not retry in a loop. mark-read will not write chat.db instead.", file=sys.stderr)
    raise SystemExit(code)


def call_jxa(payload, timeout, as_json):
    proc = subprocess.run(
        ["perl", "-e", "alarm shift @ARGV; exec @ARGV", str(timeout), "osascript", "-l", "JavaScript", str(LIB), "--", json.dumps(payload)],
        capture_output=True,
        text=True,
    )
    if proc.returncode in (-14, 142) or "Alarm clock" in (proc.stderr or ""):
        die(4, "automation_timeout", f"Timed out after {timeout}s waiting for Messages. This is a hang or a dialog, not an access denial. Do not retry in a loop.", as_json)
    if proc.returncode != 0:
        blob = (proc.stderr or proc.stdout or "osascript failed").strip()
        if "-1743" in blob or "Not authorized to send Apple events" in blob:
            die(3, "automation_denied", blob, as_json)
        if "-1712" in blob or "timed out" in blob.lower():
            die(4, "automation_timeout", blob, as_json)
        die(1, "messages_error", blob, as_json)
    raw = (proc.stdout or "").strip()
    if not raw:
        die(1, "messages_error", "Messages returned an empty response", as_json)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        die(1, "messages_error", "Messages returned non-JSON: " + raw[:200], as_json)
    return data


# The --to 1:1 send path is participant-only: never activate Messages or drive menus.
# Screen lock does not block this scripting path; -1712/exit 4 gets one unstick/relaunch and one send.
def call_send_jxa(payload, timeout, as_json):
    """Send through Messages scripting only; never activate or drive UI."""
    if payload.get("op") not in {"send_participant", "send_chat"}:
        die(2, "bad_request", "Internal send route is not a supported Messages send operation. Nothing was sent.", as_json)
    return call_jxa(payload, timeout, as_json)


def emit(data, as_json, text_fn):
    if not data.get("ok", False):
        soft = {
            "needs_force", "needs_confirm", "confirm_missing", "confirm_mismatch", "confirm_expired",
            "unsupported", "missing_target", "missing_text",
            "ambiguous", "bad_request", "not_found", "query_too_broad",
            "not_in_messages_ui", "allowlist_blocked", "text_too_long",
            "refusing_group", "both_targets", "not_frontmost", "menu_disabled",
            "menu_missing", "menu_not_clicked",
        }
        code = 2 if data.get("error") in soft else 1
        if data.get("error") == "needs_full_disk_access":
            code = 5
        if as_json:
            data.setdefault("tool", "grok-messages")
            data.setdefault("version", VERSION)
            print(json.dumps(data))
        else:
            print(f"grok-messages: {data.get('error')}: {data.get('message', '')}", file=sys.stderr)
            for row in data.get("matches") or []:
                label = row.get("name") or row.get("identifier") or row.get("guid")
                print(f"  {label}  {row.get('service')}  {row.get('filter')}  {row.get('guid')}", file=sys.stderr)
            for row in data.get("groups") or []:
                label = row.get("name") or row.get("identifier") or "(unnamed group)"
                print(f"  group  {label}  {row.get('service')}  {row.get('guid')}", file=sys.stderr)
        raise SystemExit(code)
    if as_json:
        data.setdefault("tool", "grok-messages")
        data.setdefault("version", VERSION)
        print(json.dumps(data))
    else:
        text_fn(data)


def allowlist_state():
    if not ALLOWLIST.exists():
        return {"enabled": False, "path": str(ALLOWLIST), "targets": None}
    targets = []
    for line in ALLOWLIST.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        targets.append(line)
    return {"enabled": True, "path": str(ALLOWLIST), "targets": targets}


def allowlist_allows(chat: dict) -> bool:
    state = allowlist_state()
    if not state["enabled"]:
        return True
    targets = state["targets"] or []
    if not targets:
        return False
    wanted = {db.norm_handle(item) for item in targets}
    wanted |= {item.strip() for item in targets}
    if chat["guid"] in wanted:
        return True
    if db.norm_handle(chat.get("identifier") or "") in wanted:
        return True
    for handle in chat.get("handles") or []:
        if db.norm_handle(handle) in wanted or handle in wanted:
            return True
    if chat.get("name") and chat["name"] in {item.strip() for item in targets}:
        return True
    return False


def open_db(as_json):
    try:
        return db.connect()
    except db.HistoryUnavailable as exc:
        die(5, "needs_full_disk_access", exc.message, as_json)


def cmd_doctor(args):
    as_json = args.json
    script = call_jxa({"op": "doctor"}, 30, as_json)
    if not script.get("ok", True) and script.get("error"):
        emit(script, as_json, lambda d: None)
    history = {"available": False, "source": None, "chats": None, "messages": None, "primaryChats": None}
    try:
        con = db.connect()
    except db.HistoryUnavailable as exc:
        history["message"] = exc.message
    else:
        try:
            history.update({"available": True, "source": "chat.db"})
            history.update(db.counts(con))
        finally:
            con.close()
    allow = allowlist_state()
    data = {
        "ok": True,
        "automation": "authorized",
        "backend": "messages-app-jxa+chat-db" if history["available"] else "messages-app-jxa",
        "readOnly": False,
        "sendRequiresForce": True,
        "sendRequiresConfirm": True,
        "messagesApp": {"name": script.get("name"), "version": script.get("version")},
        "scriptingChatCount": script.get("scriptingChatCount"),
        "history": {k: v for k, v in history.items() if k != "message"},
        "historyMessage": history.get("message"),
        "allowlist": {"enabled": allow["enabled"], "path": allow["path"], "count": None if allow["targets"] is None else len(allow["targets"])},
    }
    if not history["available"]:
        data["history"]["reason"] = "needs_full_disk_access"

    def text(d):
        app = d["messagesApp"]
        print(f"grok-messages {VERSION}  ok")
        print(f"Messages {app.get('version')}  scripting chats: {d.get('scriptingChatCount')}")
        print(f"automation: {d['automation']}")
        hist = d["history"]
        if hist.get("available"):
            unread_n = hist.get("unreadMessages")
            extra = f"  unread {unread_n}" if unread_n is not None else ""
            print(f"history: chat.db  chats {hist['chats']}  primary {hist['primaryChats']}  messages {hist['messages']}{extra}")
        else:
            print("history: unavailable (Full Disk Access)")
            if d.get("historyMessage"):
                print(d["historyMessage"])
        al = d["allowlist"]
        if al["enabled"]:
            print(f"allowlist: on ({al['count']} targets)  {al['path']}")
        else:
            print("allowlist: off (send still needs --force --confirm)")
        print("writes: send only with --force --confirm TOKEN from a dry-run. --force alone does not send. mark-read --force clicks enabled Conversation > Mark All as Read after Messages is frontmost. No chat.db write.")
        print("send --to is 1:1 participant only; a group needs --chat-guid")
        print("missing 1:1: a phone or email handle plus text, and only --force --confirm. The first message is the creation. A dry-run does not create a chat.")
        print("react is 1:1 only (no --chat-guid). Dry-run unless --force, which runs imsg react once. The wrap does not pre-check the lock. Vendor imsg exits -2700 if Messages is not in front.")

    emit(data, as_json, text)


def cmd_chats(args):
    as_json = args.json
    filt = "all" if args.all else args.filter
    con = open_db(as_json)
    try:
        rows = db.list_chats(con, filt, args.limit, args.query)
    finally:
        con.close()
    # inScriptingList is filled only when asked, to avoid an Apple Event on every list.
    data = {"ok": True, "filter": filt, "count": len(rows), "chats": rows}

    def text(d):
        print(f"{d['count']} chats  filter={d['filter']}")
        for chat in d["chats"]:
            label = chat.get("name") or chat.get("identifier") or "(no name)"
            print(f"{chat['lastMessageAt'] or '-':25}  {chat['service'] or '-':9}  {chat['style']:6}  {chat['messageCount']:5}  {label}")

    emit(data, as_json, text)


def _resolve(con, target, service, as_json):
    match, alts = db.resolve_chat(con, target, service)
    if alts:
        emit({
            "ok": False,
            "error": "ambiguous",
            "message": f"{len(alts)} chats match {target!r}. Pass a guid or --service.",
            "matches": [
                {"name": c["name"], "identifier": c["identifier"], "guid": c["guid"], "service": c["service"], "filter": c["filter"]}
                for c in alts[:20]
            ],
        }, as_json, lambda d: None)
    if not match:
        emit({
            "ok": False,
            "error": "not_found",
            "message": f"No chat matches {target!r}.",
        }, as_json, lambda d: None)
    return match


def cmd_recent(args):
    as_json = args.json
    con = open_db(as_json)
    try:
        chat = _resolve(con, args.to, args.service, as_json)
        rows = db.recent(con, chat, args.limit)
    finally:
        con.close()
    data = {
        "ok": True,
        "chat": {k: chat[k] for k in ("guid", "name", "identifier", "service", "style", "filter", "handles")},
        "count": len(rows),
        "messages": rows,
    }

    def text(d):
        chat = d["chat"]
        label = chat.get("name") or chat.get("identifier")
        print(f"{label}  {chat['service']}  {d['count']} messages")
        for msg in d["messages"]:
            who = "me" if msg["fromMe"] else (msg.get("handle") or "?")
            body = msg.get("text") or ""
            if msg.get("hasAttachment") and not body:
                body = "[attachment]"
            if msg.get("kind") == "reaction":
                body = f"[{msg.get('reaction')}] {body}"
            body = " ".join(body.split())
            print(f"{msg.get('at') or '-':25}  {who}: {body[:180]}")

    emit(data, as_json, text)


def cmd_search(args):
    as_json = args.json
    query = (args.query or "").strip()
    if len(query) < 2:
        die(2, "bad_request", "Search needs at least 2 characters.", as_json)
    con = open_db(as_json)
    try:
        chat = None
        if args.to:
            chat = _resolve(con, args.to, args.service, as_json)
        total, hits = db.search(con, query, args.limit, None if chat is None else chat["rowid"])
    finally:
        con.close()
    if total > 500 and not hits:
        emit({
            "ok": False,
            "error": "query_too_broad",
            "message": f"{total} messages match. Narrow the query or pass --to.",
            "count": total,
        }, as_json, lambda d: None)
    data = {"ok": True, "query": query, "count": total, "returned": len(hits), "hits": hits}

    def text(d):
        print(f"{d['count']} matches, showing {d['returned']}")
        for hit in d["hits"]:
            label = hit.get("chatName") or hit.get("chatIdentifier")
            who = "me" if hit["fromMe"] else (hit.get("handle") or "?")
            print(f"{hit.get('at') or '-':25}  {label}  {who}: {hit.get('snippet')}")

    emit(data, as_json, text)


def _chat_public(chat: dict) -> dict:
    return {k: chat[k] for k in ("guid", "name", "identifier", "service", "style", "filter")}


def _group_brief(groups: list[dict]) -> list[dict]:
    out = []
    for chat in groups[:20]:
        name = (chat.get("name") or "").strip() or None
        out.append({
            "name": name,
            "identifier": chat.get("identifier"),
            "guid": chat.get("guid"),
            "service": chat.get("service"),
            "style": chat.get("style"),
        })
    return out


def _group_only_message(target: str, groups: list[dict]) -> str:
    bits = []
    for chat in groups[:8]:
        label = (chat.get("name") or "").strip() or chat.get("identifier") or "(unnamed group)"
        bits.append(f"{label} ({chat.get('guid')})")
    listed = "; ".join(bits) if bits else "(no guid)"
    extra = ""
    if len(groups) > 8:
        extra = f" and {len(groups) - 8} more"
    return (
        f"Refusing to send to {target!r}. That is not a 1:1 chat. "
        f"It only matches a group: {listed}{extra}. "
        "Nothing was sent. A person or handle is never delivered to a group that merely includes them. "
        "To message a group on purpose, pass --chat-guid with the guid you mean."
    )


def _can_create_missing(target: str, decision: dict) -> bool:
    """A missing 1:1 may be created only for a named handle.

    A group name or a group guid is not a handle. An existing 1:1 is not missing.
    The caller must also have passed a non-empty body; cmd_send checks that first.
    """
    if not db.is_new_chat_handle(target):
        return False
    kind = decision.get("kind")
    if kind == "not_found":
        return True
    if kind == "group_only" and decision.get("reason") == "handle":
        return True
    return False


def allowlist_allows_handle(handle: str) -> bool:
    state = allowlist_state()
    if not state["enabled"]:
        return True
    targets = state["targets"] or []
    if not targets:
        return False
    wanted = {db.norm_handle(item) for item in targets}
    wanted |= {item.strip() for item in targets}
    return db.norm_handle(handle) in wanted or handle in wanted


def confirm_dir() -> Path:
    override = os.environ.get("GROK_MESSAGES_CONFIRM_DIR")
    if override:
        return Path(override)
    return Path.home() / ".config" / "grok-messages"


def confirm_file() -> Path:
    return confirm_dir() / CONFIRM_FILENAME


def recipient_binding(to: str, chat_guid: str, service: str | None) -> str:
    svc = (service or "").strip()
    if chat_guid:
        return "chat-guid:" + chat_guid + "\n" + svc
    return "to:" + to + "\n" + svc


def _same(left: str, right: str) -> bool:
    # Hash first so a shorter token cannot raise or leak its length.
    digest = hashlib.sha256
    return hmac.compare_digest(
        digest(left.encode("utf-8")).digest(),
        digest(right.encode("utf-8")).digest(),
    )


def _write_private_json(path: Path, payload: dict) -> None:
    directory = path.parent
    directory.mkdir(parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    blob = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    tmp = path.with_name("." + path.name + ".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, blob)
    finally:
        os.close(fd)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)


def _attach_confirm(preview: dict, binding: str, text: str, as_json: bool) -> None:
    preview["confirmToken"] = issue_confirm(binding, text, as_json)
    preview["confirmExpiresSeconds"] = CONFIRM_TTL_SECONDS
    preview["message"] = "dry-run: nothing was sent. Pass this confirm token to send --force --confirm TOKEN."


def issue_confirm(binding: str, text: str, as_json: bool) -> str:
    token = secrets.token_urlsafe(32)
    payload = {
        "token": token,
        "recipient": binding,
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "expires": int(time.time()) + CONFIRM_TTL_SECONDS,
    }
    try:
        _write_private_json(confirm_file(), payload)
    except OSError:
        die(1, "confirm_store", "Could not store a confirm token. Nothing was sent.", as_json)
    return token


CONFIRM_MESSAGES = {
    "needs_confirm": "Refusing to send with --force alone. Run send without --force to print a confirm token, then send --force --confirm TOKEN. Nothing was sent.",
    "confirm_missing": "No confirm token is stored. Run send without --force first. Nothing was sent.",
    "confirm_mismatch": "Confirm token does not match this recipient and text. Nothing was sent.",
    "confirm_expired": "Confirm token expired. Run send without --force again. Nothing was sent.",
}


def take_confirm(token: str, binding: str, text: str) -> str | None:
    """Return an error code, or None after consuming a matching token."""
    path = confirm_file()
    if not path.is_file():
        return "confirm_missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError):
        return "confirm_missing"
    if not isinstance(data, dict):
        return "confirm_missing"
    try:
        expires = int(data.get("expires") or 0)
    except (TypeError, ValueError):
        expires = 0
    if expires < time.time():
        try:
            path.unlink()
        except OSError:
            pass
        return "confirm_expired"
    supplied = token or ""
    if not supplied or not _same(str(data.get("token") or ""), supplied):
        return "confirm_mismatch"
    if not _same(str(data.get("recipient") or ""), binding):
        return "confirm_mismatch"
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if not _same(str(data.get("text_sha256") or ""), digest):
        return "confirm_mismatch"
    try:
        path.unlink()
    except OSError:
        return "confirm_missing"
    return None


def cmd_send(args):
    as_json = args.json
    text = args.text if args.text is not None else ""
    to = (args.to or "").strip()
    chat_guid = (args.chat_guid or "").strip()
    if to and chat_guid:
        die(2, "both_targets", "Pass either --to (a person, 1:1 only) or --chat-guid (one exact chat). Not both. Nothing was sent.", as_json)
    if not to and not chat_guid:
        die(2, "missing_target", "Pass --to with a phone, email, or 1:1 chat, or --chat-guid for one exact chat (required for a group). Nothing was sent.", as_json)
    if not str(text).strip():
        die(2, "missing_text", "Pass --text. Nothing was sent.", as_json)
    if len(text) > MAX_TEXT:
        die(2, "text_too_long", f"Text is {len(text)} characters. The cap is {MAX_TEXT}. Nothing was sent.", as_json)
    binding = recipient_binding(to, chat_guid, args.service)
    confirm = (getattr(args, "confirm", None) or "").strip()
    if args.force and not args.dry_run and not confirm:
        die(2, "needs_confirm", CONFIRM_MESSAGES["needs_confirm"], as_json)

    con = open_db(as_json)
    try:
        if chat_guid:
            match, alts = db.resolve_chat(con, chat_guid, args.service)
            if alts or not match or match.get("guid") != chat_guid:
                # resolve_chat also matches handles and names. --chat-guid is exact only.
                exact = None
                if match and match.get("guid") == chat_guid:
                    exact = match
                emit({
                    "ok": False,
                    "error": "not_found",
                    "message": f"No chat has guid {chat_guid!r}. Nothing was sent.",
                }, as_json, lambda d: None)
            chat = match
            route = "chat"
            handle = None
        else:
            decision = db.resolve_person_for_send(con, to, args.service)
            kind = decision.get("kind")
            if kind == "ambiguous":
                emit({
                    "ok": False,
                    "error": "ambiguous",
                    "message": f"{len(decision.get('matches') or [])} one-to-one chats match {to!r}. Pass a 1:1 guid via --chat-guid or --service. Groups are not candidates. Nothing was sent.",
                    "matches": [
                        {"name": c["name"], "identifier": c["identifier"], "guid": c["guid"], "service": c["service"], "filter": c["filter"], "style": c["style"]}
                        for c in (decision.get("matches") or [])[:20]
                    ],
                }, as_json, lambda d: None)
            if kind == "group_only" and not _can_create_missing(to, decision):
                groups = decision.get("groups") or []
                emit({
                    "ok": False,
                    "error": "refusing_group",
                    "message": _group_only_message(to, groups),
                    "groups": _group_brief(groups),
                }, as_json, lambda d: None)
            if kind == "direct" and decision.get("chat"):
                chat = decision["chat"]
                if db.chat_is_group(chat):
                    emit({
                        "ok": False,
                        "error": "refusing_group",
                        "message": _group_only_message(to, [chat]),
                        "groups": _group_brief([chat]),
                    }, as_json, lambda d: None)
                route = "participant"
                handle = decision.get("handle")
            elif _can_create_missing(to, decision):
                # Text was already required. Do not create when the body is missing.
                chat = None
                route = "new_participant"
                handle = db.norm_handle(to)
            else:
                emit({
                    "ok": False,
                    "error": "not_found",
                    "message": f"No 1:1 chat matches {to!r}. Nothing was sent. A missing chat is created only for a phone or email handle with text. Group chats are ignored for --to.",
                }, as_json, lambda d: None)
    finally:
        con.close()

    if route == "new_participant":
        if not allowlist_allows_handle(handle):
            die(
                2,
                "allowlist_blocked",
                f"Send blocked by {ALLOWLIST}. Add this handle, or remove the file. Nothing was sent and no chat was created.",
                as_json,
            )
    elif not allowlist_allows(chat):
        die(
            2,
            "allowlist_blocked",
            f"Send blocked by {ALLOWLIST}. Add this chat's guid or handle, or remove the file. Nothing was sent.",
            as_json,
        )

    if route == "new_participant":
        preview = {
            "ok": True,
            "sent": False,
            "dryRun": True,
            "created": False,
            "wouldCreate": True,
            "route": "new_participant",
            "handle": handle,
            "textLength": len(text),
            "group": False,
            "chat": None,
            "createMeans": "first_message",
        }
    else:
        preview = {
            "ok": True,
            "sent": False,
            "dryRun": True,
            "created": False,
            "wouldCreate": False,
            "route": route,
            "chat": _chat_public(chat),
            "textLength": len(text),
            "group": db.chat_is_group(chat),
        }
    if route == "participant":
        preview["handle"] = handle
        preview["group"] = False
    if args.dry_run or not args.force:
        # dry-run never calls Messages.send, even if --force was also passed.
        # A missing chat stops here: no resolve, no send, no create.
        # The confirm token is issued only after resolution succeeds.
        if route == "new_participant":
            _attach_confirm(preview, binding, text, as_json)

            def show_new(d):
                print(f"dry-run: no 1:1 chat for {d.get('handle')}. The first message would create it ({d['textLength']} characters).")
                print(f"confirm: {d.get('confirmToken')}")
                print("expires in 10 minutes. send --force --confirm TOKEN")
                print("nothing sent and no chat created")

            emit(preview, as_json, show_new)
            return
        if route == "participant":
            resolved = call_jxa({"op": "resolve_participant", "handle": handle, "service": chat.get("service")}, 45, as_json)
            preview["participantFound"] = bool(resolved.get("found"))
            preview["participantService"] = resolved.get("service")
            if not resolved.get("found"):
                looked = call_jxa({"op": "resolve_chat", "chatId": chat["guid"]}, 45, as_json)
                preview["directChatInScriptingList"] = bool(looked.get("found"))
                preview["scriptingGroup"] = looked.get("group")
                if looked.get("found") and looked.get("group"):
                    emit({
                        "ok": False,
                        "error": "refusing_group",
                        "message": _group_only_message(to, [chat]),
                        "groups": _group_brief([chat]),
                    }, as_json, lambda d: None)
        else:
            looked = call_jxa({"op": "resolve_chat", "chatId": chat["guid"]}, 45, as_json)
            preview["inScriptingList"] = bool(looked.get("found"))
            preview["scriptingGroup"] = looked.get("group")
            preview["participantCount"] = looked.get("participantCount")

        _attach_confirm(preview, binding, text, as_json)

        def show(d):
            chat = d["chat"]
            label = chat.get("name") or chat.get("identifier") or chat.get("guid")
            if d["route"] == "participant":
                found = "participant found" if d.get("participantFound") else "participant not in scripting list"
                print(f"dry-run: would send {d['textLength']} characters 1:1 via participant {d.get('handle')} ({found}, {chat.get('service')})")
                print(f"direct chat: {label} style={chat.get('style')} guid={chat.get('guid')}")
            else:
                kind = "group" if d.get("group") else "chat"
                print(f"dry-run: would send {d['textLength']} characters to {kind} {label} ({chat.get('service')}, {chat.get('guid')})")
            print(f"confirm: {d.get('confirmToken')}")
            print("expires in 10 minutes. send --force --confirm TOKEN")
            print("nothing sent")

        emit(preview, as_json, show)
        return

    reason = take_confirm(confirm, binding, text)
    if reason:
        die(2, reason, CONFIRM_MESSAGES[reason], as_json)

    if route == "new_participant":
        result = call_send_jxa({
            "op": "send_participant",
            "handle": handle,
            "service": args.service,
            "text": text,
            "createIfMissing": True,
        }, 45, as_json)
    elif route == "participant":
        result = call_send_jxa({
            "op": "send_participant",
            "handle": handle,
            "service": chat.get("service"),
            "directChatId": chat["guid"],
            "text": text,
        }, 45, as_json)
    else:
        result = call_send_jxa({"op": "send_chat", "chatId": chat["guid"], "text": text}, 45, as_json)
    if not result.get("ok"):
        emit(result, as_json, lambda d: None)
    data = {
        "ok": True,
        "sent": True,
        "dryRun": False,
        "route": result.get("route") or route,
        "chat": preview["chat"],
        "textLength": len(text),
        "group": bool(result.get("group")) if route == "chat" else False,
    }
    if route in {"participant", "new_participant"}:
        data["handle"] = result.get("handle") or handle
    if route == "new_participant":
        data["created"] = bool(result.get("created"))
        data["group"] = False

    def show_sent(d):
        if d.get("route") == "new_participant" or not d.get("chat"):
            created = "created the 1:1" if d.get("created") else "used an existing participant"
            print(f"sent {d['textLength']} characters 1:1 to {d.get('handle')} ({created})")
            return
        chat = d["chat"]
        label = chat.get("name") or chat.get("identifier") or chat.get("guid")
        if d["route"] == "participant":
            print(f"sent {d['textLength']} characters 1:1 to {d.get('handle')} ({label})")
        else:
            print(f"sent {d['textLength']} characters to {label} ({chat['service']}, {chat['guid']})")

    emit(data, as_json, show_sent)


PATH_WARNING = (
    "Warning: the path is a local private file. Nothing was opened, copied, or sent."
)
PATH_UNAVAILABLE = "path not available from the attachment row; nothing was searched"


def cmd_attachments(args):
    as_json = args.json
    reveal = bool(getattr(args, "reveal_path", False))
    target = (args.chat_guid or args.to or "").strip()
    if not target:
        die(2, "missing_target", "Pass --chat-guid or --to. This only lists metadata. Nothing was sent.", as_json)
    if not 1 <= args.limit <= 40:
        die(2, "bad_request", "--limit must be 1 through 40.", as_json)
    con = open_db(as_json)
    try:
        chat = _resolve(con, target, args.service, as_json)
        total, rows = db.list_attachments(con, chat["rowid"], args.limit, reveal_path=reveal)
    finally:
        con.close()
    data = {
        "ok": True,
        "readOnly": True,
        "chat": {k: chat[k] for k in ("guid", "name", "identifier", "service", "style")},
        "count": total,
        "returned": len(rows),
        "attachments": rows,
    }
    if reveal:
        data["revealPath"] = True
        data["warning"] = PATH_WARNING

    def text(d):
        label = d["chat"].get("name") or d["chat"].get("identifier") or d["chat"].get("guid")
        mode = "path reveal" if d.get("revealPath") else "metadata only"
        print(f"{label}  {d['count']} attachments, showing {d['returned']} ({mode})")
        if d.get("revealPath"):
            print(d["warning"])
        for row in d["attachments"]:
            name = row.get("name") or "(unnamed)"
            mime = row.get("mime") or "-"
            size = row.get("bytes")
            print(f"{row.get('at') or '-':25}  {mime:24}  {size if size is not None else '-'}  {name}")
            if d.get("revealPath"):
                print(f"  {row['path'] if row.get('path') else PATH_UNAVAILABLE}")

    emit(data, as_json, text)


def cmd_unread(args):
    as_json = args.json
    con = open_db(as_json)
    try:
        summary = db.unread_chats(con, args.limit)
    finally:
        con.close()
    data = {"ok": True, "readOnly": True, **summary}

    def text(d):
        print(f"{d['messages']} unread messages in {d['chats']} chats, showing {d['returned']}")
        if d.get("contactsCache"):
            print(f"contacts cache: on  names filled for {d.get('namedFromContacts')} chats in this page")
        else:
            print("contacts cache: off (chat names only; no Contacts.app call)")
        for chat in d["top"]:
            label = chat.get("name") or chat.get("identifier") or "(no name)"
            src = chat.get("nameSource") or "-"
            print(f"{chat['unread']:5}  {chat.get('service') or '-':9}  {chat.get('style') or '-':6}  {src:9}  {label}")

    emit(data, as_json, text)





UI_LIB = Path(__file__).resolve().parent / "mark_ui.js"
MARK_READ_HELP = (
    "Drives the Messages app. It does not write chat.db, send, type, or press Return, and it does not use IMCore or change SIP. "
    "Without --force, Messages is not activated and no menu is clicked. "
    "With --all --force, Messages is brought frontmost, then Conversation > Mark All as Read is clicked only after that item is enabled. "
    "Activate alone is not success. If the item never enables, the command exits non-zero and does not claim a click. "
    "--to / --chat-guid clicks Mark as Read only when that exact item is enabled. "
    "Needs Automation for Messages and Accessibility for System Events. "
    "If loginwindow is frontmost or the screensaver is running, it exits before activation with a clear locked-screen error; unread, doctor, and other non-UI commands are not blocked. "
    "The separate send command uses Messages scripting's send operation, is independently gated, and was not tested under the lock; mark-read never invokes it. "
    "The iPhone badge has to be confirmed on the phone."
)


def _ui_denied(blob: str) -> str | None:
    text = blob or ""
    if "not allowed assistive" in text or "(-25211)" in text or "(-1719)" in text or "1002" in text and "assistive" in text.lower():
        return "accessibility_denied"
    if "-1743" in text or "Not authorized to send Apple events" in text:
        return "automation_denied"
    return None


def call_mark_ui(payload, timeout, as_json):
    proc = subprocess.run(
        ["perl", "-e", "alarm shift @ARGV; exec @ARGV", str(timeout), "osascript", "-l", "JavaScript", str(UI_LIB), "--", json.dumps(payload)],
        capture_output=True,
        text=True,
    )
    blob = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
    if proc.returncode in (-14, 142) or "Alarm clock" in (proc.stderr or ""):
        die(4, "automation_timeout", f"Timed out after {timeout}s waiting for Messages. Nothing was sent.", as_json)
    denied = _ui_denied(blob)
    if proc.returncode != 0:
        if denied == "accessibility_denied":
            die(3, "accessibility_denied", blob, as_json)
        if denied == "automation_denied":
            die(3, "automation_denied", blob, as_json)
        die(1, "messages_error", blob or "osascript failed", as_json)
    raw = (proc.stdout or "").strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        die(1, "messages_error", "Messages UI returned non-JSON: " + raw[:200], as_json)
    return data


def _targets_ok(args, as_json):
    has_all = bool(args.all)
    to = (args.to or "").strip()
    chat_guid = (args.chat_guid or "").strip()
    if to and chat_guid:
        die(2, "both_targets", "Pass either --to or --chat-guid, not both. Nothing was marked read.", as_json)
    if has_all and (to or chat_guid):
        die(2, "both_targets", "Pass either --all or one chat (--to or --chat-guid), not both. Nothing was marked read.", as_json)
    if not has_all and not to and not chat_guid:
        die(2, "missing_target", "Pass --all, or --to / --chat-guid. Nothing was marked read.", as_json)
    return has_all, to, chat_guid


def cmd_mark_read(args):
    """Drive Messages menus. Never write chat.db. Never send."""
    as_json = args.json
    has_all, to, chat_guid = _targets_ok(args, as_json)
    if not args.force:
        die(
            2,
            "needs_force",
            "Refusing to drive Messages without --force. Nothing was activated, clicked, or sent. " + MARK_READ_HELP,
            as_json,
        )
    if not has_all:
        # Resolve so a bad target fails before any UI. Do not use the match to type or send.
        con = open_db(as_json)
        try:
            _resolve(con, chat_guid or to, args.service, as_json)
        finally:
            con.close()
        payload = {"op": "mark_front"}
    else:
        payload = {"op": "mark_all"}
    data = call_mark_ui(payload, 45, as_json)
    data["sent"] = False
    data["wroteDatabase"] = False
    if not (data.get("ok") and data.get("clicked") and data.get("menuEnabled") and data.get("frontmost")):
        data["ok"] = False
        data.setdefault("error", "menu_not_clicked")
        data.setdefault("message", "Did not click an enabled menu item. Nothing was sent.")
        emit(data, as_json, lambda d: None)
    data["sent"] = False
    data["wroteDatabase"] = False

    def text(d):
        print(d.get("message") or d.get("action") or "mark-read")
        print("nothing sent, chat.db not written")

    emit(data, as_json, text)


REACT_NAMES = {
    "love": "love",
    "like": "like",
    "dislike": "dislike",
    "laugh": "laugh",
    "emphasis": "emphasis",
    "emphasize": "emphasis",
    "question": "question",
}
VENDOR_IMSG = str(Path.home() / "Developer/vendor/imsg/.build/arm64-apple-macosx/release/imsg")


def _canonical_reaction(name: str) -> str | None:
    return REACT_NAMES.get((name or "").strip().casefold())


def _imsg_path() -> str | None:
    """GROK_MESSAGES_IMSG when that file is executable, else the vendored imsg 0.15.10 build.

    Never searches PATH or Homebrew. Those ship imsg 0.4.0, which has no react.
    """
    env = os.environ.get("GROK_MESSAGES_IMSG", "").strip()
    if env and os.path.isfile(env) and os.access(env, os.X_OK):
        return env
    if os.path.isfile(VENDOR_IMSG) and os.access(VENDOR_IMSG, os.X_OK):
        return VENDOR_IMSG
    return None


def _react_argv(rowid: int, reaction: str) -> list[str]:
    binary = _imsg_path() or VENDOR_IMSG
    return [binary, "react", "--chat-id", str(rowid), "--reaction", reaction]


def _react_group_message(target: str, groups: list[dict]) -> str:
    bits = []
    for chat in groups[:8]:
        label = (chat.get("name") or "").strip() or chat.get("identifier") or "(unnamed group)"
        bits.append(f"{label} ({chat.get('guid')})")
    listed = "; ".join(bits) if bits else "(no guid)"
    extra = f" and {len(groups) - 8} more" if len(groups) > 8 else ""
    return (
        f"Refusing to react in {target!r}. That is not a 1:1 chat. "
        f"It matches a group: {listed}{extra}. "
        "Nothing was reacted. react does not take --chat-guid."
    )


def _react_refuses_group(chat: dict) -> bool:
    if (chat.get("participantCount") or 0) > 1:
        return True
    if chat.get("style") == "group":
        return True
    return db.chat_is_group(chat)


def _last_non_reaction_snippet(rows: list[dict]) -> str:
    for msg in reversed(rows):
        if msg.get("kind") == "reaction":
            continue
        body = msg.get("text") or ""
        if not body and msg.get("hasAttachment"):
            body = "[attachment]"
        body = " ".join(str(body).split())
        if body:
            return body[:120]
    return ""


def cmd_react(args):
    """1:1 tapback via imsg react. Dry-run unless --force. Never writes chat.db."""
    as_json = args.json
    reaction = _canonical_reaction(args.reaction)
    if not reaction:
        die(
            2,
            "unsupported",
            "Unsupported reaction. Use love, like, dislike, laugh, emphasis, or question. emphasize is emphasis. Nothing was reacted.",
            as_json,
        )
    to = (args.to or "").strip()
    if not to:
        die(2, "missing_target", "Pass --to for a 1:1 chat. react has no --chat-guid. Nothing was reacted.", as_json)

    con = open_db(as_json)
    try:
        decision = db.resolve_person_for_send(con, to, args.service)
        kind = decision.get("kind")
        if kind == "ambiguous":
            emit({
                "ok": False,
                "error": "ambiguous",
                "message": f"{len(decision.get('matches') or [])} one-to-one chats match {to!r}. Pass --service. Groups are not candidates. Nothing was reacted.",
                "matches": [
                    {"name": c["name"], "identifier": c["identifier"], "guid": c["guid"], "service": c["service"], "filter": c["filter"], "style": c["style"]}
                    for c in (decision.get("matches") or [])[:20]
                ],
            }, as_json, lambda d: None)
        if kind == "group_only":
            groups = decision.get("groups") or []
            emit({
                "ok": False,
                "error": "refusing_group",
                "message": _react_group_message(to, groups),
                "groups": _group_brief(groups),
            }, as_json, lambda d: None)
        if kind != "direct" or not decision.get("chat"):
            emit({
                "ok": False,
                "error": "not_found",
                "message": f"No 1:1 chat matches {to!r}. Nothing was reacted. Group chats are ignored for --to.",
            }, as_json, lambda d: None)
        chat = decision["chat"]
        if _react_refuses_group(chat):
            emit({
                "ok": False,
                "error": "refusing_group",
                "message": _react_group_message(to, [chat]),
                "groups": _group_brief([chat]),
            }, as_json, lambda d: None)
        rows = db.recent(con, chat, 40)
    finally:
        con.close()

    snippet = _last_non_reaction_snippet(rows)
    argv = _react_argv(chat["rowid"], reaction)
    shown = shlex.join(argv)
    missing = _imsg_path() is None

    if not args.force:
        data = {
            "ok": True,
            "dryRun": True,
            "reacted": False,
            "sent": False,
            "reaction": reaction,
            "chatRowid": chat["rowid"],
            "snippet": snippet,
            "command": shown,
            "imsg": argv[0],
            "imsgMissing": missing,
            "group": False,
        }

        def show(d):
            print(f"dry-run: chat rowid {d['chatRowid']}  reaction {d['reaction']}")
            print(f"snippet: {d.get('snippet') or '(no non-reaction message)'}")
            print(d["command"])
            if d.get("imsgMissing"):
                print("missing: imsg binary is not executable")
            print("nothing executed")

        emit(data, as_json, show)
        return

    if missing:
        die(
            2,
            "missing_imsg",
            f"imsg react binary is missing ({argv[0]}). Nothing was reacted. No AppleScript fallback.",
            as_json,
        )

    proc = subprocess.run(argv, capture_output=True, text=True)
    if as_json:
        payload = {
            "ok": proc.returncode == 0,
            "dryRun": False,
            "reacted": proc.returncode == 0,
            "sent": False,
            "reaction": reaction,
            "chatRowid": chat["rowid"],
            "command": shown,
            "exitCode": proc.returncode,
            "stdout": proc.stdout,
            "stderr": proc.stderr,
        }
        if proc.returncode != 0:
            payload["error"] = "imsg_failed"
            payload["message"] = (proc.stderr or proc.stdout or "imsg react failed").strip()[:500]
        emit(payload, as_json, lambda d: None)
        return
    if proc.stdout:
        sys.stdout.write(proc.stdout if proc.stdout.endswith("\n") else proc.stdout + "\n")
    if proc.returncode != 0:
        err = (proc.stderr or "").strip() or "imsg react failed"
        die(proc.returncode or 1, "imsg_failed", err, False)
    print(f"reacted {reaction} in chat {chat['rowid']}")



def _read_only_target(args, as_json, idle):
    to = (getattr(args, "to", None) or "").strip()
    chat_guid = (getattr(args, "chat_guid", None) or "").strip()
    if to and chat_guid:
        die(2, "both_targets", "Pass either --to or --chat-guid, not both. " + idle, as_json)
    target = chat_guid or to
    if not target:
        die(2, "missing_target", "Pass --to or --chat-guid. " + idle, as_json)
    return target


def _history_argv(rowid: int, limit: int) -> list[str]:
    """Read-only imsg history. JSON so this process can drop bodies and paths.

    Never passes a cache-conversion flag, --db, send, react, or tapback.
    """
    binary = _imsg_path() or VENDOR_IMSG
    return [binary, "history", "--chat-id", str(int(rowid)), "--limit", str(int(limit)), "--json"]


def _watch_argv(rowid: int) -> list[str]:
    """Read-only imsg watch for one chat. No bridge events and no cache conversion."""
    binary = _imsg_path() or VENDOR_IMSG
    return [binary, "watch", "--chat-id", str(int(rowid)), "--json"]


def _basename_only(value):
    if not isinstance(value, str) or not value:
        return None
    if "/" in value:
        tail = value.rsplit("/", 1)[-1]
        return tail or None
    return value


def _redact_imsg_message(obj: dict, reveal_path: bool) -> dict:
    """Drop message text and absolute paths. Paths return only with reveal_path."""
    text = obj.get("text")
    text_s = text if isinstance(text, str) else ""
    raw_atts = obj.get("attachments") if isinstance(obj.get("attachments"), list) else []
    attachments = []
    for att in raw_atts:
        if not isinstance(att, dict):
            continue
        name = _basename_only(att.get("transfer_name")) or _basename_only(att.get("filename"))
        item = {
            "name": name,
            "mime": att.get("mime_type") or None,
            "bytes": att.get("total_bytes"),
            "sticker": bool(att.get("is_sticker")),
            "missing": bool(att.get("missing")),
        }
        if reveal_path:
            path = att.get("original_path")
            item["path"] = path if isinstance(path, str) and path else None
        attachments.append(item)
    return {
        "id": obj.get("id"),
        "chatId": obj.get("chat_id"),
        "createdAt": obj.get("created_at"),
        "fromMe": bool(obj.get("is_from_me")),
        "sender": obj.get("sender") if isinstance(obj.get("sender"), str) else None,
        "hasText": bool(text_s.strip()),
        "textLength": len(text_s),
        "reaction": bool(obj.get("is_reaction")),
        "attachmentCount": len(attachments),
        "attachments": attachments,
    }


def _parse_imsg_json_lines(stdout: str) -> list[dict]:
    rows = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows


def _run_imsg_readonly(argv: list[str]) -> tuple[int, str, str]:
    proc = subprocess.run(argv, capture_output=True, text=True)
    return proc.returncode, proc.stdout or "", proc.stderr or ""


def _stream_imsg(argv: list[str]):
    return subprocess.Popen(
        argv,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _close_stream(proc) -> None:
    if proc is None:
        return
    if proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=2)


def _print_read_row(row: dict, reveal: bool) -> None:
    who = "me" if row.get("fromMe") else (row.get("sender") or "?")
    print(
        f"{row.get('createdAt') or '-':25}  {who}  "
        f"chars {row.get('textLength')}  attachments {row.get('attachmentCount')}"
    )
    if reveal:
        for att in row.get("attachments") or []:
            print(f"  {att.get('path') if att.get('path') else PATH_UNAVAILABLE}")


def _load_chat_row(args, as_json, idle):
    target = _read_only_target(args, as_json, idle)
    con = open_db(as_json)
    try:
        chat = _resolve(con, target, getattr(args, "service", None), as_json)
    finally:
        con.close()
    return chat


def _dry_read(kind: str, argv: list[str], chat: dict, reveal: bool, as_json, extra: dict | None = None):
    missing = _imsg_path() is None
    data = {
        "ok": True,
        "dryRun": True,
        "readOnly": True,
        "executed": False,
        "kind": kind,
        "chatRowid": chat["rowid"],
        "command": shlex.join(argv),
        "imsgMissing": missing,
        "revealPath": reveal,
        "bodies": False,
    }
    if extra:
        data.update(extra)
    if reveal:
        data["warning"] = PATH_WARNING

    def show(d):
        print(f"dry-run: imsg {d['kind']}  chat rowid {d['chatRowid']}")
        print(d["command"])
        if d.get("imsgMissing"):
            print("missing: imsg binary is not executable")
        if d.get("revealPath"):
            print(d["warning"])
            print("paths are not read on a dry-run")
        print("nothing executed")
        print("message bodies are not printed")

    emit(data, as_json, show)


def _emit_read_rows(kind: str, rows: list[dict], reveal: bool, as_json, chat_rowid: int):
    data = {
        "ok": True,
        "dryRun": False,
        "readOnly": True,
        "executed": True,
        "kind": kind,
        "chatRowid": chat_rowid,
        "count": len(rows),
        "bodies": False,
        "messages": rows,
    }
    if reveal:
        data["revealPath"] = True
        data["warning"] = PATH_WARNING

    def show(d):
        print(f"{d['kind']}: {d['count']} messages (bodies hidden)")
        if d.get("revealPath"):
            print(d["warning"])
        for row in d["messages"]:
            _print_read_row(row, bool(d.get("revealPath")))

    emit(data, as_json, show)


def cmd_history(args):
    """Wrap imsg history. Dry-run unless --force. Never prints message text."""
    as_json = args.json
    reveal = bool(getattr(args, "reveal_path", False))
    idle = "Nothing was read from imsg."
    if not 1 <= args.limit <= 40:
        die(2, "bad_request", "--limit must be 1 through 40.", as_json)
    chat = _load_chat_row(args, as_json, idle)
    argv = _history_argv(chat["rowid"], args.limit)
    if not args.force:
        _dry_read("history", argv, chat, reveal, as_json, {"limit": args.limit})
        return
    if _imsg_path() is None:
        die(2, "missing_imsg", f"imsg history binary is missing ({argv[0]}). Nothing was read.", as_json)
    code, stdout, _stderr = _run_imsg_readonly(argv)
    if code != 0:
        die(code or 1, "imsg_failed", f"imsg history exited {code}. Nothing was opened.", as_json)
    rows = [_redact_imsg_message(obj, reveal) for obj in _parse_imsg_json_lines(stdout)]
    _emit_read_rows("history", rows, reveal, as_json, chat["rowid"])


def cmd_watch(args):
    """Wrap imsg watch. Opt-in: dry-run unless --force. Does not start a watch otherwise."""
    as_json = args.json
    reveal = bool(getattr(args, "reveal_path", False))
    idle = "Nothing was watched. imsg watch was not started."
    chat = _load_chat_row(args, as_json, idle)
    argv = _watch_argv(chat["rowid"])
    if not args.force:
        _dry_read("watch", argv, chat, reveal, as_json)
        return
    if _imsg_path() is None:
        die(2, "missing_imsg", f"imsg watch binary is missing ({argv[0]}). Nothing was watched.", as_json)
    proc = _stream_imsg(argv)
    rows = []
    try:
        stream = proc.stdout
        if stream is None:
            die(1, "imsg_failed", "imsg watch produced no stream. Nothing was opened.", as_json)
        for line in stream:
            line = (line or "").strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                rows.append(_redact_imsg_message(obj, reveal))
    finally:
        _close_stream(proc)
    _emit_read_rows("watch", rows, reveal, as_json, chat["rowid"])


def cmd_gaps(args):
    as_json = getattr(args, "json", False)
    data = {"ok": True, "tool": "grok-messages", "version": VERSION, "gaps": GAPS}
    if as_json:
        print(json.dumps(data))
        return
    print("grok-messages gaps")
    for item in GAPS:
        print(f"- {item}")


def build_parser():
    parser = argparse.ArgumentParser(prog="grok-messages", description="Local Apple Messages CLI")
    parser.add_argument("--version", action="version", version=f"grok-messages {VERSION}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def add_json(p):
        p.add_argument("--json", action="store_true")

    doctor = sub.add_parser("doctor")
    add_json(doctor)
    doctor.set_defaults(func=cmd_doctor)

    chats = sub.add_parser("chats")
    add_json(chats)
    chats.add_argument("--limit", type=int, default=30)
    chats.add_argument("--filter", choices=("primary", "unknown", "other"), default="primary")
    chats.add_argument("--all", action="store_true", help="Include unknown and other filters")
    chats.add_argument("--query")
    chats.set_defaults(func=cmd_chats)

    listing = sub.add_parser("list")
    add_json(listing)
    listing.add_argument("--limit", type=int, default=30)
    listing.add_argument("--filter", choices=("primary", "unknown", "other"), default="primary")
    listing.add_argument("--all", action="store_true")
    listing.add_argument("--query")
    listing.set_defaults(func=cmd_chats)

    recent = sub.add_parser("recent")
    add_json(recent)
    recent.add_argument("--to", required=True)
    recent.add_argument("--service", choices=("iMessage", "SMS", "RCS"))
    recent.add_argument("--limit", type=int, default=15)
    recent.set_defaults(func=cmd_recent)

    search = sub.add_parser("search")
    add_json(search)
    search.add_argument("query")
    search.add_argument("--to")
    search.add_argument("--service", choices=("iMessage", "SMS", "RCS"))
    search.add_argument("--limit", type=int, default=15)
    search.set_defaults(func=cmd_search)

    send = sub.add_parser(
        "send",
        help="Send plain text. --to is 1:1 only. Groups need --chat-guid.",
        description=(
            "Send plain text through Messages.app's non-UI scripting path. It never activates Messages, clicks menus, waits for a frontmost window, or uses mark-read's screen_locked guard. The --to 1:1 path is participant-only; screen lock does not block send. On AppleEvent -1712 / exit 4, quit and relaunch Messages once, make one send attempt, then stop. "
            "Send without --force is a dry-run and prints a confirm token. --force alone does not send. "
            "The only send is --force --confirm TOKEN. The token matches the recipient and the exact text and expires in 10 minutes. "
            "--dry-run never sends and never creates a chat, even with --force. "
            "A missing 1:1 is created only when --to is a phone or email handle and --text is non-empty. "
            "The scripting dictionary cannot make an empty chat, so the first message is the creation, and only --force --confirm applies it. "
            "An existing 1:1 is reused. A display name with no 1:1 is not_found. A group name or group guid is refused. "
            "--to is a person (phone, email, or the name of an existing 1:1 chat) and must never "
            "select a group, even when that handle is a member of one. The send goes to a Messages "
            "participant (one-to-one), not to a chat object that might be a group. "
            "If the person only appears in a group, that group is not the target. A phone or email handle plus text can start a separate 1:1, and only --force --confirm sends it. "
            "A group name is refused. To message a group on purpose, pass --chat-guid with that exact guid. "
            "Do not pass both --to and --chat-guid. "
            "Agents must draft the recipient and the exact text, run send without --force, wait for an explicit yes, then send --force --confirm TOKEN. "
            "Never send to a group unless the user named that group."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_json(send)
    send.add_argument("--to", help="Person only: phone, email, or a 1:1 chat name. Never a group. A missing 1:1 needs a phone or email handle plus text.")
    send.add_argument("--chat-guid", help="Exact chat guid. The only way to send to a group, and only when that group was named.")
    send.add_argument("--text", help="Plain text to send. Required. Cap is 4000 characters.")
    send.add_argument("--service", choices=("iMessage", "SMS", "RCS"), help="Limit --to to one service when several 1:1 chats match.")
    send.add_argument("--force", action="store_true", help="Send only together with --confirm TOKEN. --force alone does not send.")
    send.add_argument("--confirm", help="Confirm token printed by a dry-run. Required with --force. Bound to this recipient and the exact text. Expires in 10 minutes.")
    send.add_argument("--dry-run", action="store_true", help="Resolve the target and print a confirm token. Never sends, even with --force.")
    send.set_defaults(func=cmd_send)

    attachments = sub.add_parser(
        "attachments",
        help="Metadata for files in one chat. Does not open or send them.",
        description=(
            "Lists attachment metadata for one chat. Default output has no absolute path. "
            "--reveal-path prints the local absolute path already stored on the row and warns that it is a private file. "
            "It does not open, copy, upload, or send the file, and it does not search the disk. "
            "If the row has no stored path, the command says so and exits cleanly."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_json(attachments)
    attachments.add_argument("--to")
    attachments.add_argument("--chat-guid")
    attachments.add_argument("--service", choices=("iMessage", "SMS", "RCS"))
    attachments.add_argument("--limit", type=int, default=20)
    attachments.add_argument(
        "--reveal-path",
        action="store_true",
        help="Print the local absolute path already stored on the row. Warns that the file is private. Does not open it.",
    )
    attachments.set_defaults(func=cmd_attachments)

    unread = sub.add_parser("unread", help="Unread counts from chat.db. No message text. Does not mark read.")
    add_json(unread)
    unread.add_argument("--limit", type=int, default=20)
    unread.set_defaults(func=cmd_unread)

    mark = sub.add_parser(
        "mark-read",
        help="Drive Messages to mark chats read. Needs --force. Does not send.",
        description=MARK_READ_HELP,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_json(mark)
    mark.add_argument("--all", action="store_true", help="Activate Messages, then click Mark All as Read if that item is enabled.")
    mark.add_argument("--to", help="One chat. Clicks Mark as Read only when that exact menu item is enabled.")
    mark.add_argument("--chat-guid", help="One chat by guid. Same menu rule as --to.")
    mark.add_argument("--service", choices=("iMessage", "SMS", "RCS"))
    mark.add_argument("--force", action="store_true", help="Actually drive Messages. Without this, the UI is not touched.")
    mark.set_defaults(func=cmd_mark_read)

    react = sub.add_parser(
        "react",
        help="1:1 tapback via imsg react. Dry-run unless --force. Groups are refused.",
        description=(
            "Apply one standard tapback in a 1:1 chat by wrapping imsg react. "
            "There is no --chat-guid. A group (participant count above 1, or group style) is refused. "
            "With no --force this is a dry-run: it prints the chat rowid, a short last non-reaction snippet, "
            "the reaction, and the exact imsg command, and it does not execute anything. "
            "--force does not pre-check the screen lock and does not activate Messages. It runs imsg react once. "
            "Vendor imsg activates Messages and exits -2700 if it is not in front. "
            "Reactions: love, like, dislike, laugh, emphasis, question. emphasize is emphasis. "
            "Anything else exits 2 with error unsupported. "
            "The binary is $GROK_MESSAGES_IMSG when that path is executable, otherwise the vendored imsg 0.15.10. "
            "PATH and Homebrew imsg are not used. A missing binary still prints the command on dry-run; "
            "--force exits missing_imsg. No AppleScript fallback. "
            "This does not call imsg tapback, imsg launch, or IMCore, and it does not write chat.db. Locked-screen tapbacks stay parked: imsg tapback needs SIP disabled and imsg launch, and this wrap will not do either."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_json(react)
    react.add_argument("--to", required=True, help="Person only: phone, email, or a 1:1 chat name. Groups are refused.")
    react.add_argument("--reaction", required=True, help="love, like, dislike, laugh, emphasis, or question. emphasize means emphasis.")
    react.add_argument("--service", choices=("iMessage", "SMS", "RCS"), help="Limit --to to one service when several 1:1 chats match.")
    react.add_argument("--force", action="store_true", help="Run imsg react once. The wrap does not pre-check the lock or activate Messages. Vendor imsg may still require Messages in front. Without this, dry-run only.")
    react.set_defaults(func=cmd_react)


    history = sub.add_parser(
        "history",
        help="Read-only imsg history. Dry-run unless --force. No message text.",
        description=(
            "Wrap imsg history for one chat. Default is a dry-run: it prints the argv and does not run imsg. "
            "--force runs imsg history --json once and still omits message text. "
            "There is no imsg attachments subcommand. Attachment paths are original_path on that JSON, "
            "and they print only with --reveal-path, which does not open the file. "
            "This does not request attachment conversion, and it does not call imsg send, imsg react, imsg tapback, or imsg launch. "
            "send, react, and mark-read are unchanged."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_json(history)
    history.add_argument("--to")
    history.add_argument("--chat-guid")
    history.add_argument("--service", choices=("iMessage", "SMS", "RCS"))
    history.add_argument("--limit", type=int, default=15)
    history.add_argument("--force", action="store_true", help="Run imsg history once. Without this, dry-run only. Bodies stay hidden.")
    history.add_argument(
        "--reveal-path",
        action="store_true",
        help="With --force, print original_path from imsg JSON. Warns that the file is private. Does not open it.",
    )
    history.set_defaults(func=cmd_history)

    watch = sub.add_parser(
        "watch",
        help="Opt-in imsg watch. Dry-run unless --force. Does not start by itself.",
        description=(
            "Wrap imsg watch for one chat. Without --force it prints the argv and does not start imsg. "
            "--force streams imsg watch --json until the process ends, and still omits message text. "
            "Attachment paths need --reveal-path and are not opened. "
            "Bridge events and attachment conversion are not requested. "
            "This does not call imsg send, imsg react, imsg tapback, or imsg launch."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_json(watch)
    watch.add_argument("--to")
    watch.add_argument("--chat-guid")
    watch.add_argument("--service", choices=("iMessage", "SMS", "RCS"))
    watch.add_argument("--force", action="store_true", help="Start imsg watch. Without this, nothing is started.")
    watch.add_argument(
        "--reveal-path",
        action="store_true",
        help="With --force, print original_path from imsg JSON. Warns that the file is private. Does not open it.",
    )
    watch.set_defaults(func=cmd_watch)

    gaps = sub.add_parser("gaps")
    add_json(gaps)
    gaps.set_defaults(func=cmd_gaps)
    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    limit = getattr(args, "limit", None)
    if isinstance(limit, int):
        if limit < 1:
            die(2, "bad_request", "--limit must be at least 1.", getattr(args, "json", False))
        cap = 40 if args.cmd in ("recent", "search", "history") else (50 if args.cmd == "unread" else 200)
        if limit > cap:
            die(2, "bad_request", f"--limit {limit} is above the cap ({cap}).", getattr(args, "json", False))
    try:
        args.func(args)
    except BrokenPipeError:
        raise SystemExit(0)


if __name__ == "__main__":
    main()
