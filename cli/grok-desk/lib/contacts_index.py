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
SCHEMA = "2"
ADDRESSBOOK = Path.home() / "Library" / "Application Support" / "AddressBook"
CONTACT_ENT = 22

# Contacts stores related-name labels as _$!<Spouse>!$_. Friendly words match
# the filters Shortcuts uses. mother and father stay distinct and also match
# a parent search. brother and sister match a sibling search.
RELATED_LABELS = {
    "_$!<Parent>!$_": "parent",
    "_$!<Mother>!$_": "mother",
    "_$!<Father>!$_": "father",
    "_$!<Brother>!$_": "brother",
    "_$!<Sister>!$_": "sister",
    "_$!<Sibling>!$_": "sibling",
    "_$!<Child>!$_": "child",
    "_$!<Friend>!$_": "friend",
    "_$!<Spouse>!$_": "spouse",
    "_$!<Partner>!$_": "partner",
    "_$!<Assistant>!$_": "assistant",
    "_$!<Manager>!$_": "manager",
    "_$!<Other>!$_": "other",
}


def friendly_relationship_label(raw) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text == "missing value":
        return None
    mapped = RELATED_LABELS.get(text)
    if mapped:
        return mapped
    if text.startswith("_$!<") and text.endswith(">!$_"):
        inner = text[4:-4].strip().lower()
        return inner or None
    return text


def relationship_rows(raw_rows) -> list[dict]:
    out = []
    seen = set()
    for label, name in raw_rows:
        friendly = friendly_relationship_label(label)
        who = str(name).strip() if name else ""
        if not friendly and not who:
            continue
        key = (friendly or "", who)
        if key in seen:
            continue
        seen.add(key)
        out.append({"label": friendly, "name": who or None})
    return out


def rel_label_blob(rows: list[dict]) -> str:
    labels = []
    for row in rows:
        label = (row.get("label") or "").strip().lower()
        if label and label not in labels:
            labels.append(label)
    if not labels:
        return ""
    return "\n" + "\n".join(labels) + "\n"


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
            SELECT Z_PK, ZUNIQUEID, ZFIRSTNAME, ZMIDDLENAME, ZLASTNAME, ZORGANIZATION, ZNAME, ZNICKNAME
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
        related: dict[int, list[tuple]] = {}
        for row in con.execute(
            "SELECT ZOWNER, ZLABEL, ZNAME FROM ZABCDRELATEDNAME"
        ):
            related.setdefault(row["ZOWNER"], []).append((row["ZLABEL"], row["ZNAME"]))
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
        nickname = (row["ZNICKNAME"] or "").strip()
        rels = relationship_rows(related.get(row["Z_PK"], []))
        out[cid] = {
            "id": cid,
            "name": name,
            "org": (row["ZORGANIZATION"] or "").strip(),
            "nickname": nickname,
            "relationships": rels,
            "rel_labels": rel_label_blob(rels),
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
            if card["nickname"] and not prev["nickname"]:
                prev["nickname"] = card["nickname"]
            for rel in card["relationships"]:
                if rel not in prev["relationships"]:
                    prev["relationships"].append(rel)
            prev["rel_labels"] = rel_label_blob(prev["relationships"])
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
              nickname TEXT,
              relationships TEXT,
              rel_labels TEXT,
              phones TEXT,
              emails TEXT
            );
            """
        )
        con.executemany(
            "INSERT INTO contacts(id, name, org, nickname, relationships, rel_labels, phones, emails) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    card["id"],
                    card["name"],
                    card["org"],
                    card.get("nickname") or None,
                    json.dumps(card.get("relationships") or []),
                    card.get("rel_labels") or "",
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
