#!/usr/bin/env python3
"""Offline nickname and relationship filters. Fake cards only. Does not open Contacts."""
from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

CONTACTS_LIB = Path(__file__).resolve().parents[1] / "lib"
DESK_LIB = Path(__file__).resolve().parents[2] / "grok-desk" / "lib"
sys.path.insert(0, str(DESK_LIB))
sys.path.insert(0, str(CONTACTS_LIB))

import cache as contactcache  # noqa: E402
import cli  # noqa: E402
import contacts_index  # noqa: E402


def check(failures, name, cond):
    if cond:
        print("ok", name)
    else:
        failures.append(name)
        print("FAIL", name)


def write_meta(con, schema):
    con.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    for key, value in (
        ("status", "ok"),
        ("indexed_at", "2026-10-03T00:00:00-05:00"),
        ("opt_in", "1"),
        ("schema", schema),
    ):
        con.execute("INSERT INTO meta(key, value) VALUES (?, ?)", (key, value))


def schema2(path: Path):
    con = sqlite3.connect(path)
    write_meta(con, "2")
    con.execute(
        """
        CREATE TABLE contacts (
          id TEXT PRIMARY KEY,
          name TEXT,
          org TEXT,
          nickname TEXT,
          relationships TEXT,
          rel_labels TEXT,
          phones TEXT,
          emails TEXT
        )
        """
    )
    rows = [
        (
            "id-alex",
            "Alex Example",
            "Example Co",
            "Ace",
            json.dumps([
                {"label": "spouse", "name": "Sam Example"},
                {"label": "brother", "name": "Pat Example"},
            ]),
            "\nspouse\nbrother\n",
            "[]",
            "[]",
        ),
        (
            "id-blake",
            "Blake Example",
            "",
            None,
            "[]",
            "",
            "[]",
            "[]",
        ),
        (
            "id-dana",
            "Dana Example",
            "",
            "Quinn",
            json.dumps([{"label": "mother", "name": "Jordan Example"}]),
            "\nmother\n",
            "[]",
            "[]",
        ),
        (
            "id-ace",
            "Ace Person",
            "",
            None,
            "[]",
            "",
            "[]",
            "[]",
        ),
    ]
    con.executemany(
        "INSERT INTO contacts(id, name, org, nickname, relationships, rel_labels, phones, emails) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    con.commit()
    con.close()


def schema1(path: Path):
    con = sqlite3.connect(path)
    write_meta(con, "1")
    con.execute(
        """
        CREATE TABLE contacts (
          id TEXT PRIMARY KEY,
          name TEXT,
          org TEXT,
          phones TEXT,
          emails TEXT
        )
        """
    )
    con.execute(
        "INSERT INTO contacts(id, name, org, phones, emails) VALUES (?, ?, ?, ?, ?)",
        ("id-alex", "Alex Example", "Example Co", "[]", "[]"),
    )
    con.commit()
    con.close()


def run_cli(argv):
    out = io.StringIO()
    err = io.StringIO()
    code = 0
    with redirect_stdout(out), redirect_stderr(err):
        try:
            cli.main(list(argv))
        except SystemExit as exc:
            code = exc.code if exc.code is not None else 0
    return code, out.getvalue(), err.getvalue()


def main():
    failures = []
    check(failures, "version is 0.1.4", cli.VERSION == "0.1.4")
    parser = cli.build_parser()
    search = next(action for action in parser._subparsers._actions if getattr(action, "choices", None) and "search" in action.choices)
    field = next(a for a in search.choices["search"]._actions if getattr(a, "dest", None) == "field")
    check(failures, "field choices", set(field.choices) == {"name", "phone", "email", "nickname", "relationship"})

    check(failures, "spouse label", contacts_index.friendly_relationship_label("_$!<Spouse>!$_") == "spouse")
    check(failures, "mother label", contacts_index.friendly_relationship_label("_$!<Mother>!$_") == "mother")
    check(failures, "empty label", contacts_index.friendly_relationship_label("  ") is None)

    with tempfile.TemporaryDirectory() as tmp:
        store = Path(tmp) / "book.sqlite"
        con = sqlite3.connect(store)
        con.execute(
            """
            CREATE TABLE ZABCDRECORD (
              Z_PK INTEGER, Z_ENT INTEGER, ZUNIQUEID TEXT, ZFIRSTNAME TEXT, ZMIDDLENAME TEXT,
              ZLASTNAME TEXT, ZORGANIZATION TEXT, ZNAME TEXT, ZNICKNAME TEXT
            )
            """
        )
        con.execute("CREATE TABLE ZABCDPHONENUMBER (ZOWNER INTEGER, ZFULLNUMBER TEXT)")
        con.execute("CREATE TABLE ZABCDEMAILADDRESS (ZOWNER INTEGER, ZADDRESS TEXT)")
        con.execute("CREATE TABLE ZABCDRELATEDNAME (ZOWNER INTEGER, ZLABEL TEXT, ZNAME TEXT)")
        con.execute(
            "INSERT INTO ZABCDRECORD VALUES (1, 22, 'id-alex', 'Alex', '', 'Example', 'Example Co', '', 'Ace')"
        )
        con.execute(
            "INSERT INTO ZABCDRECORD VALUES (2, 22, 'id-blake', 'Blake', '', 'Example', '', '', '')"
        )
        con.execute("INSERT INTO ZABCDRELATEDNAME VALUES (1, '_$!<Spouse>!$_', 'Sam Example')")
        con.execute("INSERT INTO ZABCDRELATEDNAME VALUES (1, '_$!<Brother>!$_', '')")
        con.commit()
        con.close()
        loaded = contacts_index._load_store(store)
        alex = loaded["id-alex"]
        blake = loaded["id-blake"]
        check(failures, "loaded nickname", alex["nickname"] == "Ace")
        check(failures, "empty nickname stays empty", blake["nickname"] == "")
        labels = [row["label"] for row in alex["relationships"]]
        names = [row["name"] for row in alex["relationships"]]
        check(failures, "loaded spouse and brother", labels == ["spouse", "brother"])
        check(failures, "blank related name stays empty", names[1] is None)
        check(failures, "related name kept", names[0] == "Sam Example")
        check(failures, "blake has no relationships", blake["relationships"] == [])

        index = Path(tmp) / "index.sqlite"
        schema2(index)
        contactcache.DB = index
        cli.contactcache.DB = index

        nick = contactcache.search("Ace", field="nickname")
        check(failures, "nickname hits Alex", nick["ok"] and [r["id"] for r in nick["matches"]] == ["id-alex"])
        check(failures, "nickname row value", nick["matches"][0]["nickname"] == "Ace")
        named = contactcache.search("Ace", field="name")
        check(failures, "name field does not use nickname", named["ok"] and [r["id"] for r in named["matches"]] == ["id-ace"])
        spouse = contactcache.search("spouse", field="relationship")
        check(failures, "spouse filter", spouse["ok"] and [r["id"] for r in spouse["matches"]] == ["id-alex"])
        sibling = contactcache.search("sibling", field="relationship")
        check(failures, "sibling matches brother", sibling["ok"] and [r["id"] for r in sibling["matches"]] == ["id-alex"])
        parent = contactcache.search("parent", field="relationship")
        check(failures, "parent matches mother", parent["ok"] and [r["id"] for r in parent["matches"]] == ["id-dana"])
        manager = contactcache.search("manager", field="relationship")
        check(failures, "manager empty", manager["ok"] and manager["count"] == 0)
        shown = contactcache.show(None, "id-alex")
        contact = shown["contact"]
        check(failures, "show nickname", contact.get("nickname") == "Ace")
        check(failures, "show relationships", [r["label"] for r in contact.get("relationships")] == ["spouse", "brother"])
        blank = contactcache.show(None, "id-blake")
        check(failures, "show empty nickname", blank["contact"].get("nickname") is None)
        check(failures, "show empty relationships", blank["contact"].get("relationships") == [])

        calls = []

        def fake_jxa(payload, timeout, as_json):
            calls.append(payload)
            return {"ok": True, "query": payload.get("query"), "field": payload.get("field"), "count": 0, "matches": []}

        cli.call_jxa = fake_jxa
        cli.wake_contacts = lambda: calls.append({"op": "wake"})

        code, out, err = run_cli(["search", "spouse", "--field", "relationship", "--json"])
        data = json.loads(out)
        check(failures, "cli spouse json", code == 0 and data["count"] == 1 and data["matches"][0]["relationships"][0]["label"] == "spouse")
        check(failures, "cli spouse did not call contacts", calls == [])

        code, out, err = run_cli(["search", "spouse", "--field", "relationship", "--live"])
        check(failures, "live relationship refused", code == 2 and "unsupported_field" in err)
        check(failures, "live relationship made no call", calls == [])

        code, out, err = run_cli(["show", "--id", "id-blake"])
        check(failures, "show text omits empty nickname", code == 0 and "nickname:" not in out and "relationship" not in out)
        code, out, err = run_cli(["show", "--id", "id-alex"])
        check(failures, "show text nickname", "nickname: Ace" in out)
        check(failures, "show text spouse", "relationship (spouse): Sam Example" in out)
        check(failures, "show text blank brother", "relationship (brother):" in out)

        old = Path(tmp) / "old.sqlite"
        schema1(old)
        contactcache.DB = old
        cli.contactcache.DB = old
        stale = contactcache.search("Ace", field="nickname")
        check(failures, "old index nickname needs reindex", stale.get("error") == "needs_reindex")
        stale_rel = contactcache.search("spouse", field="relationship")
        check(failures, "old index relationship needs reindex", stale_rel.get("error") == "needs_reindex")
        still = contactcache.search("Alex", field="name")
        check(failures, "old index name still works", still.get("ok") and still["matches"][0]["id"] == "id-alex")
        check(failures, "old index does not invent nickname", "nickname" not in still["matches"][0])
        shown_old = contactcache.show(None, "id-alex")
        check(failures, "old show has note", "fieldsNote" in shown_old and "nickname" not in shown_old["contact"])

        calls.clear()
        code, out, err = run_cli(["search", "Ace", "--field", "nickname", "--json"])
        check(failures, "old nickname falls through live", code == 0 and calls and calls[-1].get("field") == "nickname")
        calls.clear()
        code, out, err = run_cli(["search", "spouse", "--field", "relationship"])
        check(failures, "old relationship does not call contacts", code == 2 and calls == [] and "needs_reindex" in err)

    if failures:
        print("FAILED", ", ".join(failures))
        raise SystemExit(1)
    print("all ok")


if __name__ == "__main__":
    main()
