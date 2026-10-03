"""Optional contacts cache. Off unless explicitly requested.

Reads AddressBook stores read-only. Writes only ~/.cache/grok-contacts.
Does not upload. Does not call Contacts.app (no Automation dialog).
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from common import db_path, now_iso, secure_db, secure_dir

CACHE_NAME = "grok-contacts"
SCHEMA = "1"
ADDRESSBOOK = Path.home() / "Library" / "Application Support" / "AddressBook"
CONTACT_ENT = 22


def _sources() -> list[Path]:
    found = []
    main = ADDRESSBOOK / "AddressBook-v22.abcddb"
    if main.exists():
        found.append(main)
    sources = ADDRESSBOOK / "Sources"
    if sources.exists():
        found.extend(sorted(sources.glob("*/AddressBook-v22.abcddb")))
    return found


def _load_store(path: Path) -> dict[str, dict]:
    uri = f"file:{path}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only=ON")
    try:
        people = con.execute(
            """
            SELECT Z_PK, ZUNIQUEID, ZFIRSTNAME, ZMIDDLENAME, ZLASTNAME, ZORGANIZATION, ZNAME
            FROM ZABCDRECORD
            WHERE Z_ENT = ?
            """,
            (CONTACT_ENT,),
        ).fetchall()
        phones: dict[int, list[str]] = {}
        for row in con.execute(
            "SELECT ZOWNER, ZFULLNUMBER FROM ZABCDPHONENUMBER "
            "WHERE ZFULLNUMBER IS NOT NULL AND ZFULLNUMBER != ''"
        ):
            phones.setdefault(row["ZOWNER"], [])
            number = str(row["ZFULLNUMBER"]).strip()
            if number and number not in phones[row["ZOWNER"]]:
                phones[row["ZOWNER"]].append(number)
        emails: dict[int, list[str]] = {}
        for row in con.execute(
            "SELECT ZOWNER, ZADDRESS FROM ZABCDEMAILADDRESS "
            "WHERE ZADDRESS IS NOT NULL AND ZADDRESS != ''"
        ):
            emails.setdefault(row["ZOWNER"], [])
            address = str(row["ZADDRESS"]).strip()
            if address and address not in emails[row["ZOWNER"]]:
                emails[row["ZOWNER"]].append(address)
    finally:
        con.close()
    out = {}
    for row in people:
        cid = (row["ZUNIQUEID"] or "").strip()
        if not cid:
            continue
        parts = [row["ZFIRSTNAME"], row["ZMIDDLENAME"], row["ZLASTNAME"]]
        name = " ".join(str(p).strip() for p in parts if p and str(p).strip())
        if not name:
            name = (row["ZNAME"] or "").strip()
        out[cid] = {
            "id": cid,
            "name": name,
            "org": (row["ZORGANIZATION"] or "").strip(),
            "phones": phones.get(row["Z_PK"], []),
            "emails": emails.get(row["Z_PK"], []),
        }
    return out


def build() -> dict:
    path = db_path(CACHE_NAME)
    merged: dict[str, dict] = {}
    warnings = []
    stores = _sources()
    if not stores:
        return {
            "ok": False,
            "surface": "contacts",
            "error": "no_addressbook",
            "message": "No AddressBook store was readable. Nothing was written.",
        }
    for store in stores:
        try:
            loaded = _load_store(store)
        except sqlite3.OperationalError:
            warnings.append("unreadable_store")
            continue
        for cid, card in loaded.items():
            prev = merged.get(cid)
            if prev is None:
                merged[cid] = card
                continue
            if len(card["name"]) > len(prev["name"]):
                prev["name"] = card["name"]
            if card["org"] and not prev["org"]:
                prev["org"] = card["org"]
            for number in card["phones"]:
                if number not in prev["phones"]:
                    prev["phones"].append(number)
            for address in card["emails"]:
                if address not in prev["emails"]:
                    prev["emails"].append(address)
    secure_dir(path.parent)
    con = sqlite3.connect(path)
    try:
        con.execute("PRAGMA journal_mode=DELETE")
        con.executescript(
            """
            DROP TABLE IF EXISTS contacts;
            DROP TABLE IF EXISTS meta;
            CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE contacts (
              id TEXT PRIMARY KEY,
              name TEXT,
              org TEXT,
              phones TEXT,
              emails TEXT
            );
            """
        )
        con.executemany(
            "INSERT INTO contacts(id, name, org, phones, emails) VALUES (?, ?, ?, ?, ?)",
            [
                (
                    card["id"],
                    card["name"],
                    card["org"],
                    json.dumps(card["phones"]),
                    json.dumps(card["emails"]),
                )
                for card in merged.values()
            ],
        )
        indexed_at = now_iso()
        phone_cards = sum(1 for card in merged.values() if card["phones"])
        email_cards = sum(1 for card in merged.values() if card["emails"])
        for key, value in {
            "schema": SCHEMA,
            "indexed_at": indexed_at,
            "opt_in": "1",
            "status": "ok",
            "stores": str(len(stores)),
        }.items():
            con.execute("INSERT INTO meta(key, value) VALUES(?, ?)", (key, value))
        con.commit()
        count = con.execute("SELECT count(*) FROM contacts").fetchone()[0]
    finally:
        con.close()
        secure_db(path)
    return {
        "ok": True,
        "surface": "contacts",
        "path": str(path),
        "contacts": count,
        "withPhones": phone_cards,
        "withEmails": email_cards,
        "indexedAt": indexed_at,
        "warnings": len(warnings),
        "optIn": True,
    }
