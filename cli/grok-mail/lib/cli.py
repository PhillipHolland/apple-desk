#!/usr/bin/env python3
"""grok-mail command line. Mail.app via JXA. Not a cloud mail API. Does not send."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

VERSION = "0.1.2"
LIB = Path(__file__).resolve().parent / "mail.js"
TOOL = "grok-mail"

GAPS = [
    "Prefer the Gmail connector for cloud mail. grok-mail is only for Mail.app on this Mac.",
    "Direct MailCore / the files under ~/Library/Mail are not used. This CLI asks Mail.app over Apple Events. The grant is Automation (Grok Bot / Grok Bot Helper → Mail). A separate compose entitlement can still block draft --force even after reads work.",
    "Send is not implemented. There is no send subcommand and the JXA never calls Mail's send command. draft --force only saves an unsent outgoing message (intended for Drafts) with the window hidden. Agents must not add a send path without an explicit user yes.",
    "draft without --force does not talk to Mail at all. It exits needs_force and creates nothing. draft --dry-run also skips Mail.",
    "list and search do not return message bodies. show returns one body clipped to 800 characters. No raw source, no full header dump, no attachments, and no attachment download.",
    "draft --force clips body to 4000 characters. Longer bodies are refused with bad_request before Mail is called.",
    "search matches subject and sender in one mailbox (default INBOX). It does not search bodies, recipients, or every mailbox. A match set over 300 messages is refused instead of dumped.",
    "list returns at most 50 messages (default 20), newest-last in Mail's scripting order, reversed so the last rows come first. It does not page a whole mailbox.",
    "Mailbox names other than the unified Inbox, Drafts, Sent, Junk, Trash, and Outbox are matched inside Mail's mailbox tree. Duplicate names need --account. Nested paths use slash names when you know them.",
    "No rules, signatures, VIP, flags beyond read/flagged on show, move, delete, junk training, or mailbox create.",
    "IMAP mailboxes that are not fully downloaded can make list, search, or show slow or time out. A timeout exits 4 once. Do not retry in a loop while a permission dialog is up.",
    "Account passwords, SMTP servers, and usernames are never read. accounts returns name, id, type, enabled, and email addresses only.",
]

AUTH_HINT = (
    "If a dialog is on screen: the calling app wants access to control “Mail”. Click Allow once.\n"
    "If it is gone: System Settings → Privacy & Security → Automation → Grok Bot (and Grok Bot Helper) → turn Mail on.\n"
    "Stop. Do not retry doctor in a loop while AFK. Prefer the Gmail connector for cloud Gmail."
)

DOCTOR_TIMEOUT = 20
DEFAULT_TIMEOUT = 20
LONG_TIMEOUT = 25
BODY_CLIP = 800
DRAFT_BODY_MAX = 4000


def die(code, error, message, as_json):
    authish = error in ("automation_denied", "automation_timeout")
    payload = {
        "ok": False,
        "tool": TOOL,
        "version": VERSION,
        "error": error,
        "code": code,
        "message": message,
    }
    if authish:
        payload["hint"] = AUTH_HINT
        payload["settings"] = AUTH_HINT
    if as_json:
        print(json.dumps(payload))
    else:
        print(f"grok-mail: {error}", file=sys.stderr)
        if message:
            print(message, file=sys.stderr)
        if authish:
            print(AUTH_HINT, file=sys.stderr)
    raise SystemExit(code)


def call_jxa(payload, timeout, as_json):
    proc = subprocess.run(
        ["perl", "-e", "alarm shift @ARGV; exec @ARGV", str(timeout), "osascript", "-l", "JavaScript", str(LIB), "--", json.dumps(payload)],
        capture_output=True,
        text=True,
    )
    blob = ((proc.stderr or "") + "\n" + (proc.stdout or "")).strip()
    if proc.returncode in (-14, 142) or "Alarm clock" in blob:
        die(4, "automation_timeout", f"Timed out after {timeout}s waiting for Mail. A permission dialog may be waiting. Stop; do not retry in a loop.", as_json)
    if proc.returncode != 0:
        if "-1743" in blob or "Not authorized to send Apple events" in blob:
            die(3, "automation_denied", blob, as_json)
        if "-1712" in blob or "timed out" in blob.lower():
            die(4, "automation_timeout", blob + " Stop; do not retry in a loop.", as_json)
        die(1, "mail_error", blob or "osascript failed", as_json)
    raw = (proc.stdout or "").strip()
    if not raw:
        die(1, "mail_error", "Mail returned an empty response", as_json)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        die(1, "mail_error", "Mail returned non-JSON: " + raw[:400], as_json)
    if data.get("error") == "automation_denied":
        die(3, "automation_denied", data.get("message") or "", as_json)
    if data.get("error") == "automation_timeout":
        die(4, "automation_timeout", (data.get("message") or "") + " Stop; do not retry in a loop.", as_json)
    return data


def emit(data, as_json, text_fn):
    if not data.get("ok", False):
        soft = {
            "needs_force", "unsupported", "missing_target", "missing_to",
            "missing_subject", "missing_query", "ambiguous", "bad_request",
            "not_found", "query_too_broad",
        }
        code = 2 if data.get("error") in soft else 1
        if data.get("error") == "automation_denied":
            code = 3
        if data.get("error") == "automation_timeout":
            code = 4
        if as_json:
            data.setdefault("tool", TOOL)
            data.setdefault("version", VERSION)
            data.setdefault("code", code)
            data.setdefault("message", "")
            if data.get("error") in ("automation_denied", "automation_timeout"):
                data.setdefault("hint", AUTH_HINT)
            print(json.dumps(data))
        else:
            print(f"grok-mail: {data.get('error')}: {data.get('message', '')}", file=sys.stderr)
            for row in data.get("matches") or []:
                label = row.get("name") or row.get("subject") or "(untitled)"
                extra = row.get("account") or ""
                print(f"  {label}  {extra}".rstrip(), file=sys.stderr)
            if data.get("error") in ("automation_denied", "automation_timeout"):
                print(AUTH_HINT, file=sys.stderr)
        raise SystemExit(code)
    if as_json:
        data.setdefault("tool", TOOL)
        data.setdefault("version", VERSION)
        print(json.dumps(data))
    else:
        text_fn(data)


def clamp_limit(n, as_json):
    if n is None:
        return 20
    if n < 1 or n > 50:
        die(2, "bad_request", "--limit must be 1..50 so a mailbox is not dumped.", as_json)
    return n


def print_doctor(data):
    app = data.get("mailApp") or {}
    print(f"grok-mail {VERSION}  ok")
    print("backend: Mail.app JXA")
    print(f"automation: {data.get('automation')}")
    print("sends: no (draft --force only, and only with --force)")
    print(f"Mail {app.get('version')} ({app.get('id')})")
    print(f"accounts: {data.get('accounts')}   inbox unread: {data.get('inboxUnread')}")


def print_accounts(data):
    print(f"{data.get('count')} account(s)")
    for row in data.get("accounts") or []:
        emails = ", ".join(row.get("emails") or [])
        flag = "enabled" if row.get("enabled") else "disabled"
        print(f"  {row.get('name')}  {flag}  {row.get('accountType') or ''}  {emails}")


def print_mailboxes(data):
    print(f"{data.get('count')} mailbox(es)")
    for row in data.get("mailboxes") or []:
        indent = "  " * (1 + int(row.get("depth") or 0))
        unread = row.get("unread")
        extra = f"  unread {unread}" if unread not in (None, 0) else ""
        print(f"{indent}{row.get('name')}  · {row.get('account')}{extra}")
    if data.get("truncated"):
        print("(list truncated)")


def print_messages(data):
    label = data.get("mailbox") or ""
    if data.get("query"):
        print(f"{data.get('returned')} shown, {data.get('count')} match(es) for {data.get('query')!r} in {label}")
    else:
        print(f"{data.get('returned')} message(s) in {label}  (mailbox has {data.get('mailboxCount')})")
    for row in data.get("messages") or []:
        when = str(row.get("dateReceived") or row.get("dateSent") or "")[:16].replace("T", " ")
        print(f"  {when}  {row.get('subject') or '(no subject)'}  · {row.get('sender') or ''}  {row.get('id')}")
    if data.get("truncated"):
        print("(pass a smaller mailbox or a tighter query; bodies are not included)")


def print_show(data):
    msg = data.get("message") or {}
    print(msg.get("subject") or "(no subject)")
    print(f"id: {msg.get('id')}")
    print(f"from: {msg.get('sender')}")
    print(f"date: {msg.get('dateReceived')}")
    print(f"mailbox: {msg.get('mailbox')}")
    print(f"read: {msg.get('read')}  flagged: {msg.get('flagged')}")
    body = msg.get("body") or ""
    if body:
        print("---")
        print(body)


def print_draft(data):
    if data.get("created"):
        print(f"draft saved  id {data.get('id')}  to {data.get('to')}  subject {data.get('subject')}")
        print("not sent")
        return
    print(data.get("message") or "dry-run")


def add_json(sp):
    sp.add_argument("--json", action="store_true")


def build_parser():
    p = argparse.ArgumentParser(prog="grok-mail", description="Mail.app CLI (JXA). Read by default. Does not send.")
    p.add_argument("--version", action="version", version=f"grok-mail {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("doctor", help="Check Automation access once")
    add_json(sp)

    sp = sub.add_parser("accounts", help="List Mail accounts (no passwords)")
    add_json(sp)

    sp = sub.add_parser("mailboxes", help="List mailbox names (no messages)")
    sp.add_argument("--account", help="exact account name")
    add_json(sp)

    sp = sub.add_parser("list", help="Subjects, dates, and senders only")
    sp.add_argument("--mailbox", default="INBOX")
    sp.add_argument("--account")
    sp.add_argument("--limit", type=int, default=20)
    add_json(sp)

    sp = sub.add_parser("show", help="One message by Mail id; body is truncated")
    sp.add_argument("--id", required=True, type=int)
    sp.add_argument("--mailbox")
    sp.add_argument("--account")
    add_json(sp)

    sp = sub.add_parser("search", help="Subject or sender in one mailbox")
    sp.add_argument("query")
    sp.add_argument("--mailbox", default="INBOX")
    sp.add_argument("--account")
    sp.add_argument("--limit", type=int, default=20)
    add_json(sp)

    sp = sub.add_parser("draft", help="Save an unsent draft. Requires --force. Never sends.")
    sp.add_argument("--to", required=True)
    sp.add_argument("--subject", required=True)
    sp.add_argument("--body", default="")
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--dry-run", action="store_true", help="Validate args only; do not call Mail.app")
    add_json(sp)

    sp = sub.add_parser("gaps", help="What Mail.app can do that this CLI cannot")
    add_json(sp)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    as_json = getattr(args, "json", False)
    if args.cmd == "gaps":
        data = {"ok": True, "tool": TOOL, "version": VERSION, "gaps": GAPS}
        emit(data, as_json, lambda d: print("\n".join("- " + g for g in d["gaps"])))
        return

    if args.cmd == "draft":
        body = args.body or ""
        if len(body) > DRAFT_BODY_MAX:
            die(2, "bad_request", f"draft --body is capped at {DRAFT_BODY_MAX} characters. Nothing was created.", as_json)
        if args.dry_run:
            subject = (args.subject or "").strip()
            if not subject:
                die(2, "missing_subject", "draft needs --subject. Mail was not called.", as_json)
            bad = []
            for raw in (args.to or "").split(","):
                addr = raw.strip()
                if addr and "@" not in addr:
                    bad.append(addr)
            if bad:
                die(2, "bad_request", "Each --to address needs an @. Mail was not called.", as_json)
            data = {
                "ok": True,
                "dryRun": True,
                "wouldCreate": True,
                "sent": False,
                "to": args.to,
                "subject": subject,
                "bodyChars": len(body),
                "message": "dry-run: Mail.app was not called. draft still needs --force to create.",
            }
            emit(data, as_json, print_draft)
            return
        if not args.force:
            die(
                2,
                "needs_force",
                "draft refuses without --force. Nothing was created and Mail was not called. "
                "--force saves an unsent message in Mail (window hidden). grok-mail never sends. "
                "Prefer the Gmail connector for cloud Gmail.",
                as_json,
            )

    if args.cmd == "doctor":
        data = call_jxa({"op": "doctor"}, DOCTOR_TIMEOUT, as_json)
        data["version"] = VERSION
        emit(data, as_json, print_doctor)
        return
    if args.cmd == "accounts":
        data = call_jxa({"op": "accounts"}, DEFAULT_TIMEOUT, as_json)
        emit(data, as_json, print_accounts)
        return
    if args.cmd == "mailboxes":
        data = call_jxa({"op": "mailboxes", "account": args.account}, LONG_TIMEOUT, as_json)
        emit(data, as_json, print_mailboxes)
        return
    if args.cmd == "list":
        data = call_jxa({
            "op": "list",
            "mailbox": args.mailbox,
            "account": args.account,
            "limit": clamp_limit(args.limit, as_json),
        }, LONG_TIMEOUT, as_json)
        emit(data, as_json, print_messages)
        return
    if args.cmd == "show":
        data = call_jxa({
            "op": "show",
            "id": args.id,
            "mailbox": args.mailbox,
            "account": args.account,
        }, LONG_TIMEOUT, as_json)
        emit(data, as_json, print_show)
        return
    if args.cmd == "search":
        data = call_jxa({
            "op": "search",
            "query": args.query,
            "mailbox": args.mailbox,
            "account": args.account,
            "limit": clamp_limit(args.limit, as_json),
        }, LONG_TIMEOUT, as_json)
        emit(data, as_json, print_messages)
        return
    if args.cmd == "draft":
        data = call_jxa({
            "op": "draft",
            "to": args.to,
            "subject": args.subject,
            "body": args.body,
            "force": True,
        }, LONG_TIMEOUT, as_json)
        emit(data, as_json, print_draft)
        return
    die(2, "bad_request", "Unknown command", as_json)


if __name__ == "__main__":
    main()
