#!/usr/bin/env python3
"""grok-contacts command line. Contacts.app via JXA. Not a cloud API."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

VERSION = "0.1.1"
LIB = Path(__file__).resolve().parent / "contacts.js"

GAPS = [
    "Direct CNContactStore is not used. A command-line binary has no NSContactsUsageDescription, so macOS often will not show the Contacts privacy prompt. This CLI asks Contacts.app over Apple Events instead. The grant is Automation (Grok Bot or Terminal → Contacts), same shape as grok-notes.",
    "Search matches name, first name, last name, organization, and nickname only. Phone and email search is refused on purpose: Contacts whose() cannot filter phones (error -2700), and walking every card is about 70ms each (several minutes for this book) and would load every number into the scripting process. search --field phone|email exits unsupported_field and does not call Contacts. show still returns phones for one id.",
    "search and groups never print phone numbers, emails, or street addresses. show does, for one card.",
    "No account picker. Contacts scripting returns the unified cards Contacts.app shows, not a per-iCloud-account split.",
    "Cannot merge, unlink, or split linked contacts. Cannot ignore Siri suggestions or the Duplicates pile.",
    "No contact photo, poster, Memoji, pronunciation, or name title/prefix write path beyond the fields create/update list.",
    "Smart lists, emergency contacts, medical ID, and the share-contact sheet are not scriptable here.",
    "Group membership on show is skipped when there are more than 80 groups, so a card's groups may be empty even if it belongs to some.",
    "Deleting a group does not delete the people in it. delete of a person removes that card.",
    "No bulk export and no vCard import. Image and vCard properties are intentionally not returned.",
]


def die(code, error, message, as_json):
    if as_json:
        print(json.dumps({
            "ok": False,
            "tool": "grok-contacts",
            "version": VERSION,
            "error": error,
            "code": code,
            "message": message,
        }))
    else:
        print(f"grok-contacts: {error}", file=sys.stderr)
        if message:
            print(message, file=sys.stderr)
        if error in ("automation_denied", "automation_timeout"):
            print("If a dialog is on screen: “Grok Bot” wants access to control “Contacts”. Click Allow.", file=sys.stderr)
            print("If it is gone: System Settings → Privacy & Security → Automation → Grok Bot (or Terminal) → Contacts on.", file=sys.stderr)
            print("That is Automation, not the separate Contacts privacy list.", file=sys.stderr)
    raise SystemExit(code)


def call_jxa(payload, timeout, as_json):
    proc = subprocess.run(
        ["perl", "-e", "alarm shift @ARGV; exec @ARGV", str(timeout), "osascript", "-l", "JavaScript", str(LIB), "--", json.dumps(payload)],
        capture_output=True,
        text=True,
    )
    if proc.returncode in (-14, 142) or "Alarm clock" in (proc.stderr or ""):
        die(4, "automation_timeout", f"Timed out after {timeout}s waiting for Contacts. A permission dialog may be waiting.", as_json)
    if proc.returncode != 0:
        blob = (proc.stderr or proc.stdout or "osascript failed").strip()
        if "-1743" in blob or "Not authorized to send Apple events" in blob:
            die(3, "automation_denied", blob, as_json)
        if "-1712" in blob or "timed out" in blob.lower():
            die(4, "automation_timeout", blob, as_json)
        die(1, "contacts_error", blob, as_json)
    raw = (proc.stdout or "").strip()
    if not raw:
        die(1, "contacts_error", "Contacts returned an empty response", as_json)
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        die(1, "contacts_error", "Contacts returned non-JSON: " + raw[:400], as_json)
    return data


def emit(data, as_json, text_fn):
    if not data.get("ok", False):
        soft = {
            "needs_force", "needs_allow_large", "unsupported", "missing_target",
            "missing_name", "missing_change", "missing_query", "ambiguous",
            "bad_request", "not_found", "already_exists", "query_too_broad",
            "unsupported_field",
        }
        code = 2 if data.get("error") in soft else 1
        if as_json:
            data.setdefault("tool", "grok-contacts")
            data.setdefault("version", VERSION)
            print(json.dumps(data))
        else:
            print(f"grok-contacts: {data.get('error')}: {data.get('message', '')}", file=sys.stderr)
            matches = data.get("matches") or []
            for row in matches:
                print(f"  {row.get('name') or '(no name)'}  {row.get('id')}", file=sys.stderr)
        raise SystemExit(code)
    if as_json:
        data.setdefault("tool", "grok-contacts")
        data.setdefault("version", VERSION)
        print(json.dumps(data))
    else:
        text_fn(data)


def parse_labeled(values, default_label):
    rows = []
    for raw in values or []:
        if ":" in raw:
            label, value = raw.split(":", 1)
            label = label.strip() or default_label
            value = value.strip()
        else:
            label, value = default_label, raw.strip()
        if not value:
            die(2, "bad_request", f"Empty value in {raw!r}. Use label:value.", False)
        rows.append({"label": label, "value": value})
    return rows


def print_doctor(data):
    app = data.get("contactsApp") or {}
    print(f"grok-contacts {VERSION}  ok")
    print("backend: Contacts.app JXA")
    print(f"automation: {data.get('automation')}")
    print("writes: enabled (delete still needs --force)")
    print(f"Contacts {app.get('version')} ({app.get('id')})")
    print(f"people: {data.get('people')}   groups: {data.get('groups')}   me card: {data.get('hasMeCard')}")


def print_groups(data):
    print(f"{data.get('count')} groups")
    for row in data.get("groups") or []:
        print(f"  {row.get('name')}  {row.get('id')}")
    if data.get("truncated"):
        print("(list truncated; pass --limit)")


def print_search(data):
    print(f"{data.get('count')} match(es) for {data.get('query')!r}")
    for row in data.get("matches") or []:
        extra = row.get("organization") or ""
        suffix = f"  · {extra}" if extra and extra != row.get("name") else ""
        print(f"  {row.get('name')}{suffix}  {row.get('id')}")
    if data.get("truncated"):
        print("(showing the first matches; pass --limit or a narrower name)")
    print("No phone numbers or emails in search results. Use show --id for one card.")


def print_show(data):
    c = data.get("contact") or {}
    print(c.get("name") or "(no name)")
    print(f"id: {c.get('id')}")
    bits = []
    if c.get("organization"):
        bits.append(c["organization"])
    if c.get("jobTitle"):
        bits.append(c["jobTitle"])
    if bits:
        print("  " + " · ".join(bits))
    for key, title in (("phones", "phone"), ("emails", "email"), ("urls", "url")):
        for row in c.get(key) or []:
            print(f"  {title} ({row.get('label') or 'other'}): {row.get('value')}  [{row.get('id')}]")
    for row in c.get("addresses") or []:
        formatted = row.get("formatted") or ", ".join(
            x for x in (row.get("street"), row.get("city"), row.get("state"), row.get("zip"), row.get("country")) if x
        )
        print(f"  address ({row.get('label') or 'other'}): {formatted}")
    if c.get("note"):
        print("  note: " + c["note"][:300])
    groups = c.get("groups") or []
    if groups:
        print("  groups: " + ", ".join(g.get("name") or "" for g in groups))


def print_write(data):
    if data.get("deleted"):
        print(f"deleted {data.get('name')}  {data.get('id')}")
        if "membersKept" in data:
            print(f"people kept in Contacts: {data.get('membersKept')}")
        return
    print(f"{data.get('name')}  {data.get('id')}")


def build_parser():
    p = argparse.ArgumentParser(prog="grok-contacts", description="Contacts.app CLI (JXA). Read by default.")
    p.add_argument("--version", action="version", version=f"grok-contacts {VERSION}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_json(sp):
        sp.add_argument("--json", action="store_true")

    sp = sub.add_parser("doctor", help="Check Automation access and counts")
    add_json(sp)

    sp = sub.add_parser("search", help="Find contacts by name or organization. Phone and email are refused.")
    sp.add_argument("query")
    sp.add_argument("--field", choices=("name", "phone", "email"), default="name")
    sp.add_argument("--limit", type=int, default=20)
    add_json(sp)

    sp = sub.add_parser("show", help="One contact, including phones and emails")
    sp.add_argument("query", nargs="?")
    sp.add_argument("--id")
    add_json(sp)

    sp = sub.add_parser("groups", help="List group names and ids")
    sp.add_argument("--limit", type=int, default=200)
    add_json(sp)

    sp = sub.add_parser("list", help="Alias of groups")
    sp.add_argument("--limit", type=int, default=200)
    add_json(sp)

    sp = sub.add_parser("create", help="Create one contact")
    sp.add_argument("--first")
    sp.add_argument("--last")
    sp.add_argument("--middle")
    sp.add_argument("--org")
    sp.add_argument("--job")
    sp.add_argument("--nickname")
    sp.add_argument("--department")
    sp.add_argument("--note")
    sp.add_argument("--company", action="store_true")
    sp.add_argument("--phone", action="append", help="label:number (default label mobile)")
    sp.add_argument("--email", action="append", help="label:address (default label home)")
    sp.add_argument("--url", action="append", help="label:url")
    sp.add_argument("--group", action="append")
    add_json(sp)

    sp = sub.add_parser("update", help="Change one contact by id")
    sp.add_argument("--id", required=True)
    sp.add_argument("--first")
    sp.add_argument("--last")
    sp.add_argument("--middle")
    sp.add_argument("--org")
    sp.add_argument("--job")
    sp.add_argument("--nickname")
    sp.add_argument("--department")
    sp.add_argument("--note")
    sp.add_argument("--company", action="store_true")
    sp.add_argument("--not-company", action="store_true")
    sp.add_argument("--add-phone", action="append")
    sp.add_argument("--add-email", action="append")
    sp.add_argument("--add-url", action="append")
    sp.add_argument("--remove-id", action="append", help="phone, email, url, or address id")
    sp.add_argument("--group", action="append", help="add to this group")
    add_json(sp)

    sp = sub.add_parser("delete", help="Delete one contact by id")
    sp.add_argument("--id", required=True)
    sp.add_argument("--force", action="store_true")
    add_json(sp)

    sp = sub.add_parser("create-group")
    sp.add_argument("name")
    add_json(sp)

    sp = sub.add_parser("delete-group")
    sp.add_argument("name", nargs="?")
    sp.add_argument("--id")
    sp.add_argument("--force", action="store_true")
    sp.add_argument("--allow-large", action="store_true")
    add_json(sp)

    sp = sub.add_parser("add-to-group")
    sp.add_argument("--id", required=True)
    sp.add_argument("--group", required=True)
    add_json(sp)

    sp = sub.add_parser("remove-from-group")
    sp.add_argument("--id", required=True)
    sp.add_argument("--group", required=True)
    add_json(sp)

    sp = sub.add_parser("gaps", help="What Contacts.app can do that this CLI cannot")
    add_json(sp)
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    as_json = getattr(args, "json", False)
    if args.cmd == "gaps":
        data = {"ok": True, "tool": "grok-contacts", "version": VERSION, "gaps": GAPS}
        emit(data, as_json, lambda d: print("\n".join("- " + g for g in d["gaps"])))
        return

    timeout = 25 if args.cmd == "doctor" else 45
    if args.cmd in ("doctor",):
        payload = {"op": "doctor"}
        data = call_jxa(payload, timeout, as_json)
        data["version"] = VERSION
        emit(data, as_json, print_doctor)
        return
    if args.cmd in ("groups", "list"):
        data = call_jxa({"op": "groups", "limit": args.limit}, timeout, as_json)
        emit(data, as_json, print_groups)
        return
    if args.cmd == "search":
        field = getattr(args, "field", "name") or "name"
        if field in ("phone", "email"):
            die(
                2,
                "unsupported_field",
                "Phone and email search is not available. Contacts scripting cannot filter those fields "
                "(whose() raises -2700), and scanning every card would load the whole book into the scripting "
                "process. Pass a name, then show --id for one card. Nothing was queried.",
                as_json,
            )
        data = call_jxa({"op": "search", "query": args.query, "limit": args.limit}, timeout, as_json)
        emit(data, as_json, print_search)
        return
    if args.cmd == "show":
        data = call_jxa({"op": "show", "query": args.query, "id": args.id}, 60, as_json)
        emit(data, as_json, print_show)
        return
    if args.cmd == "create":
        if not (args.first or args.last or args.org):
            die(2, "missing_name", "create needs --first, --last, or --org.", as_json)
        payload = {
            "op": "create",
            "first": args.first,
            "last": args.last,
            "middle": args.middle,
            "org": args.org,
            "job": args.job,
            "nickname": args.nickname,
            "department": args.department,
            "note": args.note,
            "company": bool(args.company),
            "phones": parse_labeled(args.phone, "mobile"),
            "emails": parse_labeled(args.email, "home"),
            "urls": parse_labeled(args.url, "homepage"),
            "groups": args.group or [],
        }
        data = call_jxa(payload, timeout, as_json)
        emit(data, as_json, print_write)
        return
    if args.cmd == "update":
        company = None
        if args.company and args.not_company:
            die(2, "bad_request", "Pass only one of --company and --not-company.", as_json)
        if args.company:
            company = True
        elif args.not_company:
            company = False
        payload = {
            "op": "update",
            "id": args.id,
            "first": args.first,
            "last": args.last,
            "middle": args.middle,
            "org": args.org,
            "job": args.job,
            "nickname": args.nickname,
            "department": args.department,
            "note": args.note,
            "company": company,
            "phones": parse_labeled(args.add_phone, "mobile"),
            "emails": parse_labeled(args.add_email, "home"),
            "urls": parse_labeled(args.add_url, "homepage"),
            "removeIds": args.remove_id or [],
            "groups": args.group or [],
        }
        data = call_jxa(payload, timeout, as_json)
        emit(data, as_json, print_write)
        return
    if args.cmd == "delete":
        if not args.force:
            die(2, "needs_force", "delete refuses without --force. This removes the contact from Contacts.", as_json)
        data = call_jxa({"op": "delete", "id": args.id, "force": True}, timeout, as_json)
        emit(data, as_json, print_write)
        return
    if args.cmd == "create-group":
        data = call_jxa({"op": "create-group", "name": args.name}, timeout, as_json)
        emit(data, as_json, print_write)
        return
    if args.cmd == "delete-group":
        if not args.force:
            die(2, "needs_force", "delete-group refuses without --force. People in the group are not deleted.", as_json)
        if not args.name and not args.id:
            die(2, "missing_name", "delete-group needs a name or --id.", as_json)
        data = call_jxa({
            "op": "delete-group",
            "name": args.name,
            "id": args.id,
            "force": args.force,
            "allowLarge": args.allow_large,
        }, timeout, as_json)
        emit(data, as_json, print_write)
        return
    if args.cmd in ("add-to-group", "remove-from-group"):
        data = call_jxa({"op": args.cmd, "id": args.id, "group": args.group}, timeout, as_json)
        emit(data, as_json, lambda d: print(("added to " if d.get("added") else "removed from ") + str(d.get("group"))))
        return
    die(2, "bad_request", "Unknown command", as_json)


if __name__ == "__main__":
    main()
