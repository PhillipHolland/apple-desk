#!/usr/bin/env python3
"""grok-messages command line. Send via Messages.app. History via chat.db."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import db

VERSION = "0.2.7"
LIB = Path(__file__).resolve().parent / "messages.js"
ALLOWLIST = Path.home() / ".config" / "grok-messages" / "allowlist"
MAX_TEXT = 4000

GAPS = [
    "Messages 26 scripting can list chats (id, name, participants) and send text to an existing chat. It cannot read message history. History comes from ~/Library/Messages/chat.db and needs Full Disk Access for the process that runs this CLI (Grok Bot Helper when an agent runs it).",
    "Send only works for a chat currently in the Messages scripting list. Unknown-sender and junk chats are often absent there, so history can show them while send returns not_in_messages_ui. Nothing is sent in that case.",
    "send --to is a person only (phone, email, or a 1:1 chat). It never targets a group, even when that handle is a member of one. The send uses Messages' participant object (1:1). If the handle exists only in a group, send refuses and names that group's guid. Group sends require --chat-guid, which the user must name on purpose. This CLI does not create groups.",
    "attachments lists metadata for one chat (name, mime, bytes, sticker, date). It does not download, open, or copy the file, and it does not return the absolute path. Send still cannot attach a file. No tapbacks, stickers-as-send, message effects, edits, unsends, or replies. Send is plain text only, capped at 4000 characters.",
    "No pin, mute, hide alerts, or Focus filter changes. mark-read does not write chat.db and does not use IMCore. With --force it makes Messages frontmost, then clicks an enabled Conversation > Mark All as Read. Activate alone is not success. It does not send.",
    "Search looks at the message text column only. Attachment-only rows and a few attributed-body-only rows have null text and will not match. Snippets are capped.",
    "Reactions are labeled (love, like, dislike, laugh, emphasize, question, emoji) from the row itself. The message that was reacted to is not pulled in.",
    "An optional allowlist file (~/.config/grok-messages/allowlist) restricts send targets if it exists. One handle or chat guid per line. If the file exists and has no targets, every send is refused. If the file does not exist, --force is the only gate.",
    "There is no cloud iMessage API here. This does not talk to iCloud.com.",
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


def call_send_jxa(payload, timeout, as_json):
    """Send through Messages scripting only; never activate or drive UI."""
    if payload.get("op") not in {"send_participant", "send_chat"}:
        die(2, "bad_request", "Internal send route is not a supported Messages send operation. Nothing was sent.", as_json)
    return call_jxa(payload, timeout, as_json)


def emit(data, as_json, text_fn):
    if not data.get("ok", False):
        soft = {
            "needs_force", "unsupported", "missing_target", "missing_text",
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
            print("allowlist: off (send still needs --force)")
        print("writes: send only with --force. mark-read --force clicks enabled Conversation > Mark All as Read after Messages is frontmost. No chat.db write.")
        print("send --to is 1:1 participant only; a group needs --chat-guid")

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
    if not args.force and not args.dry_run:
        die(2, "needs_force", "Refusing to send without --force. Nothing was sent. Draft the recipient and text and wait for an explicit yes.", as_json)

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
            if kind == "group_only":
                groups = decision.get("groups") or []
                emit({
                    "ok": False,
                    "error": "refusing_group",
                    "message": _group_only_message(to, groups),
                    "groups": _group_brief(groups),
                }, as_json, lambda d: None)
            if kind != "direct" or not decision.get("chat"):
                emit({
                    "ok": False,
                    "error": "not_found",
                    "message": f"No 1:1 chat matches {to!r}. Nothing was sent. Group chats are ignored for --to.",
                }, as_json, lambda d: None)
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
    finally:
        con.close()

    if not allowlist_allows(chat):
        die(
            2,
            "allowlist_blocked",
            f"Send blocked by {ALLOWLIST}. Add this chat's guid or handle, or remove the file. Nothing was sent.",
            as_json,
        )

    preview = {
        "ok": True,
        "sent": False,
        "dryRun": True,
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
            print("nothing sent")

        emit(preview, as_json, show)
        return

    if route == "participant":
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
    if route == "participant":
        data["handle"] = result.get("handle") or handle

    def show_sent(d):
        chat = d["chat"]
        label = chat.get("name") or chat.get("identifier") or chat.get("guid")
        if d["route"] == "participant":
            print(f"sent {d['textLength']} characters 1:1 to {d.get('handle')} ({label})")
        else:
            print(f"sent {d['textLength']} characters to {label} ({chat['service']}, {chat['guid']})")

    emit(data, as_json, show_sent)


def cmd_attachments(args):
    as_json = args.json
    target = (args.chat_guid or args.to or "").strip()
    if not target:
        die(2, "missing_target", "Pass --chat-guid or --to. This only lists metadata. Nothing was sent.", as_json)
    if not 1 <= args.limit <= 40:
        die(2, "bad_request", "--limit must be 1 through 40.", as_json)
    con = open_db(as_json)
    try:
        chat = _resolve(con, target, args.service, as_json)
        total, rows = db.list_attachments(con, chat["rowid"], args.limit)
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

    def text(d):
        label = d["chat"].get("name") or d["chat"].get("identifier") or d["chat"].get("guid")
        print(f"{label}  {d['count']} attachments, showing {d['returned']} (metadata only)")
        for row in d["attachments"]:
            name = row.get("name") or "(unnamed)"
            mime = row.get("mime") or "-"
            size = row.get("bytes")
            print(f"{row.get('at') or '-':25}  {mime:24}  {size if size is not None else '-'}  {name}")

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
            "Send plain text through Messages.app's non-UI scripting path. It never activates Messages, clicks menus, waits for a frontmost window, or uses mark-read's screen_locked guard. Nothing is sent unless --force is set. "
            "--dry-run never sends, even with --force. "
            "--to is a person (phone, email, or the name of an existing 1:1 chat) and must never "
            "select a group, even when that handle is a member of one. The send goes to a Messages "
            "participant (one-to-one), not to a chat object that might be a group. "
            "If the person only appears in a group, send refuses and prints that group's name and guid. "
            "To message a group on purpose, pass --chat-guid with that exact guid. "
            "Do not pass both --to and --chat-guid. "
            "Agents must draft the recipient and the exact text and wait for an explicit yes before --force. "
            "Never send to a group unless the user named that group."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    add_json(send)
    send.add_argument("--to", help="Person only: phone, email, or a 1:1 chat name. Never a group.")
    send.add_argument("--chat-guid", help="Exact chat guid. The only way to send to a group, and only when that group was named.")
    send.add_argument("--text", help="Plain text to send. Required. Cap is 4000 characters.")
    send.add_argument("--service", choices=("iMessage", "SMS", "RCS"), help="Limit --to to one service when several 1:1 chats match.")
    send.add_argument("--force", action="store_true", help="Actually send. Without this, nothing is sent.")
    send.add_argument("--dry-run", action="store_true", help="Resolve the target and print the route. Never sends, even with --force.")
    send.set_defaults(func=cmd_send)

    attachments = sub.add_parser("attachments", help="Metadata for files in one chat. Does not open or send them.")
    add_json(attachments)
    attachments.add_argument("--to")
    attachments.add_argument("--chat-guid")
    attachments.add_argument("--service", choices=("iMessage", "SMS", "RCS"))
    attachments.add_argument("--limit", type=int, default=20)
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
        cap = 40 if args.cmd in ("recent", "search") else (50 if args.cmd == "unread" else 200)
        if limit > cap:
            die(2, "bad_request", f"--limit {limit} is above the cap ({cap}).", getattr(args, "json", False))
    try:
        args.func(args)
    except BrokenPipeError:
        raise SystemExit(0)


if __name__ == "__main__":
    main()
