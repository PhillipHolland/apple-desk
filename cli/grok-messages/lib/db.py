"""Read-only chat.db access. Never writes the database. Never sends."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

APPLE = datetime(2001, 1, 1, tzinfo=timezone.utc)
CHICAGO = ZoneInfo("America/Chicago")
DB_PATH = Path.home() / "Library" / "Messages" / "chat.db"

FILTER_NAMES = {0: "primary", 1: "unknown", 2: "other"}
STYLE_NAMES = {43: "group", 45: "direct"}
REACTION_NAMES = {
    2000: "love",
    2001: "like",
    2002: "dislike",
    2003: "laugh",
    2004: "emphasize",
    2005: "question",
    2006: "emoji",
    1000: "sticker",
}


class HistoryUnavailable(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


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
    dt = (APPLE + timedelta(seconds=seconds)).astimezone(CHICAGO)
    return dt.isoformat(timespec="seconds")


def connect():
    path = DB_PATH
    if not path.exists():
        raise HistoryUnavailable(
            f"No {path}. Messages history is not on this Mac."
        )
    uri = f"file:{path}?mode=ro"
    try:
        con = sqlite3.connect(uri, uri=True, timeout=5)
    except sqlite3.Error as exc:
        raise HistoryUnavailable(_fda_message(exc)) from exc
    try:
        con.execute("select 1 from chat limit 1").fetchone()
    except sqlite3.Error as exc:
        con.close()
        raise HistoryUnavailable(_fda_message(exc)) from exc
    con.row_factory = sqlite3.Row
    return con


def _fda_message(exc: BaseException) -> str:
    return (
        "Cannot read ~/Library/Messages/chat.db (Full Disk Access). "
        f"{exc}. Send can still work through Messages.app. "
        "To enable history: System Settings → Privacy & Security → Full Disk Access, "
        "turn on Grok Bot and Grok Bot Helper (the process that runs this CLI), then quit and reopen Grok Bot. "
        "Do not grant FDA by copying chat.db somewhere else."
    )


def counts(con) -> dict:
    chats = con.execute("select count(*) from chat").fetchone()[0]
    messages = con.execute("select count(*) from message").fetchone()[0]
    primary = con.execute("select count(*) from chat where is_filtered = 0").fetchone()[0]
    return {"chats": chats, "messages": messages, "primaryChats": primary}


def _handles(blob):
    if not blob:
        return []
    return [part for part in str(blob).split("\n") if part]


def _chat_row(row) -> dict:
    style = row["style"]
    filt = row["is_filtered"]
    name = row["display_name"] or ""
    return {
        "guid": row["guid"],
        "rowid": row["rowid"],
        "name": name or None,
        "identifier": row["chat_identifier"],
        "service": row["service_name"],
        "style": STYLE_NAMES.get(style, f"style-{style}"),
        "filter": FILTER_NAMES.get(filt, f"filter-{filt}"),
        "handles": _handles(row["handles"]),
        "participantCount": len(_handles(row["handles"])),
        "messageCount": row["message_count"] or 0,
        "lastMessageAt": apple_to_iso(row["last_date"]),
    }


_CHAT_SQL = """
select
  c.ROWID as rowid,
  c.guid as guid,
  c.chat_identifier as chat_identifier,
  c.display_name as display_name,
  c.service_name as service_name,
  c.style as style,
  c.is_filtered as is_filtered,
  (select group_concat(h.id, char(10))
     from chat_handle_join j
     join handle h on h.ROWID = j.handle_id
     where j.chat_id = c.ROWID) as handles,
  (select count(*) from chat_message_join j where j.chat_id = c.ROWID) as message_count,
  (select max(j.message_date) from chat_message_join j where j.chat_id = c.ROWID) as last_date
from chat c
"""


def list_chats(con, filt: str, limit: int, query: str | None) -> list[dict]:
    sql = _CHAT_SQL
    params: list = []
    where = []
    if filt != "all":
        wanted = {"primary": 0, "unknown": 1, "other": 2}.get(filt)
        if wanted is None:
            raise ValueError(filt)
        where.append("c.is_filtered = ?")
        params.append(wanted)
    if query:
        where.append(
            "(c.display_name like ? escape '\\' or c.chat_identifier like ? escape '\\' "
            "or c.guid like ? escape '\\' or exists ("
            "select 1 from chat_handle_join j join handle h on h.ROWID = j.handle_id "
            "where j.chat_id = c.ROWID and h.id like ? escape '\\'))"
        )
        like = _like(query)
        params.extend([like, like, like, like])
    if where:
        sql += " where " + " and ".join(where)
    sql += " order by last_date desc nulls last, c.ROWID desc limit ?"
    params.append(limit)
    return [_chat_row(row) for row in con.execute(sql, params)]


def _like(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def norm_handle(value: str) -> str:
    raw = value.strip()
    if "@" in raw:
        return raw.lower()
    digits = "".join(ch for ch in raw if ch.isdigit())
    if raw.startswith("+") and digits:
        return "+" + digits
    if len(digits) == 10:
        return "+1" + digits
    if len(digits) == 11 and digits.startswith("1"):
        return "+" + digits
    return raw


def chat_is_group(chat: dict) -> bool:
    """True for group threads. Style 43 is group; style 45 is direct.

    A handle that merely sits in a group must not count as that person's 1:1 chat.
    """
    style = chat.get("style")
    if style == "group":
        return True
    if style == "direct":
        return False
    guid = chat.get("guid") or ""
    if ";+;" in guid:
        return True
    if ";-;" in guid:
        return False
    if (chat.get("participantCount") or 0) > 1:
        return True
    ident = (chat.get("identifier") or "").lower()
    if ident.startswith("chat"):
        return True
    return False


def send_handle_for(target: str, chat: dict) -> str:
    """Handle to pass to Messages' participant send. Never a group chat id."""
    raw = (target or "").strip()
    if raw and ";" not in raw and not raw.lower().startswith("chat"):
        if "@" in raw or any(ch.isdigit() for ch in raw):
            return norm_handle(raw)
    ident = chat.get("identifier") or ""
    if ident and ";" not in ident and not ident.lower().startswith("chat"):
        return norm_handle(ident)
    handles = chat.get("handles") or []
    if len(handles) == 1:
        return norm_handle(handles[0])
    return norm_handle(ident) if ident else raw


def resolve_person_for_send(con, target: str, service: str | None) -> dict:
    """Resolve --to for send. Never returns a group chat.

    kind is direct, ambiguous, group_only, or not_found.
    """
    target = target.strip()
    if not target:
        return {"kind": "not_found", "groups": [], "matches": []}
    rows = [_chat_row(r) for r in con.execute(_CHAT_SQL)]
    service_l = service.lower() if service else None

    def by_service(items):
        if not service_l:
            return items
        return [item for item in items if (item["service"] or "").lower() == service_l]

    def split(items):
        directs, groups = [], []
        for item in items:
            if chat_is_group(item):
                groups.append(item)
            else:
                directs.append(item)
        return directs, groups

    def direct_result(directs):
        chosen, alts = _prefer(directs) if len(directs) != 1 else (directs[0], [])
        if len(directs) == 1:
            chosen, alts = directs[0], []
        if alts or chosen is None:
            return {"kind": "ambiguous", "matches": alts or directs, "groups": [], "chat": None, "handle": None}
        return {
            "kind": "direct",
            "chat": chosen,
            "handle": send_handle_for(target, chosen),
            "groups": [],
            "matches": [],
        }

    exact = [c for c in rows if c["guid"] == target]
    if exact:
        directs, groups = split(exact)
        if directs:
            return direct_result(directs)
        return {"kind": "group_only", "groups": groups, "matches": [], "chat": None, "handle": None, "reason": "guid"}

    ident = norm_handle(target)
    ident_hits = [
        c for c in rows
        if norm_handle(c["identifier"] or "") == ident
        or ident in {norm_handle(h) for h in c["handles"]}
        or (c["identifier"] or "") == target
    ]
    ident_hits = by_service(ident_hits)
    directs, groups = split(ident_hits)
    if directs:
        return direct_result(directs)
    if groups:
        return {"kind": "group_only", "groups": groups, "matches": [], "chat": None, "handle": None, "reason": "handle"}

    folded = target.strip().casefold()
    name_hits = by_service([c for c in rows if (c["name"] or "").strip().casefold() == folded])
    directs, groups = split(name_hits)
    if directs:
        return direct_result(directs)
    if groups:
        return {"kind": "group_only", "groups": groups, "matches": [], "chat": None, "handle": None, "reason": "name"}
    return {"kind": "not_found", "groups": [], "matches": [], "chat": None, "handle": None}


def resolve_chat(con, target: str, service: str | None) -> tuple[dict | None, list[dict]]:
    """Return (match, candidates). candidates is set when the name is ambiguous."""
    target = target.strip()
    if not target:
        return None, []
    rows = [_chat_row(r) for r in con.execute(_CHAT_SQL)]
    service_l = service.lower() if service else None

    def by_service(items):
        if not service_l:
            return items
        return [item for item in items if (item["service"] or "").lower() == service_l]

    exact_guid = [c for c in rows if c["guid"] == target]
    if exact_guid:
        return exact_guid[0], []

    ident = norm_handle(target)
    ident_hits = [
        c for c in rows
        if norm_handle(c["identifier"] or "") == ident
        or ident in {norm_handle(h) for h in c["handles"]}
        or (c["identifier"] or "") == target
    ]
    ident_hits = by_service(ident_hits)
    if len(ident_hits) == 1:
        return ident_hits[0], []
    if len(ident_hits) > 1:
        return _prefer(ident_hits)

    folded = target.strip().casefold()
    name_hits = [c for c in rows if (c["name"] or "").strip().casefold() == folded]
    name_hits = by_service(name_hits)
    if len(name_hits) == 1:
        return name_hits[0], []
    if len(name_hits) > 1:
        return None, name_hits
    return None, []


def _prefer(items: list[dict]) -> tuple[dict | None, list[dict]]:
    rank = {"iMessage": 0, "RCS": 1, "SMS": 2}
    filt = {"primary": 0, "unknown": 1, "other": 2}
    ordered = sorted(items, key=lambda c: (filt.get(c["filter"], 9), rank.get(c["service"], 9)))
    best = ordered[0]
    tied = [
        c for c in ordered
        if c["filter"] == best["filter"] and c["service"] == best["service"]
    ]
    if len(tied) == 1:
        return tied[0], []
    return None, tied


def recent(con, chat: dict, limit: int) -> list[dict]:
    sql = """
    select
      m.guid as guid,
      m.date as date,
      m.is_from_me as is_from_me,
      m.text as text,
      m.cache_has_attachments as has_attachments,
      m.is_system_message as is_system,
      m.associated_message_type as assoc_type,
      m.associated_message_emoji as assoc_emoji,
      m.service as service,
      h.id as handle
    from chat_message_join cm
    join message m on m.ROWID = cm.message_id
    left join handle h on h.ROWID = m.handle_id
    where cm.chat_id = ?
    order by m.date desc
    limit ?
    """
    rows = list(con.execute(sql, (chat["rowid"], limit)))
    rows.reverse()
    out = []
    for row in rows:
        text = row["text"]
        clipped = False
        if isinstance(text, str) and len(text) > 2000:
            text = text[:2000]
            clipped = True
        assoc = row["assoc_type"] or 0
        kind = "message"
        reaction = None
        if assoc in REACTION_NAMES:
            reaction = REACTION_NAMES[assoc]
            kind = "sticker" if assoc == 1000 else "reaction"
        elif assoc:
            kind = "annotation"
        elif row["is_system"]:
            kind = "system"
        out.append({
            "id": row["guid"],
            "at": apple_to_iso(row["date"]),
            "fromMe": bool(row["is_from_me"]),
            "handle": None if row["is_from_me"] else row["handle"],
            "text": text,
            "truncated": clipped,
            "hasAttachment": bool(row["has_attachments"]),
            "kind": kind,
            "reaction": reaction,
            "emoji": row["assoc_emoji"],
            "service": row["service"],
        })
    return out


def search(con, query: str, limit: int, chat_rowid: int | None):
    like = _like(query)
    count_sql = "select count(*) from message m where m.text like ? escape '\\'"
    params: list = [like]
    if chat_rowid is not None:
        count_sql = """
        select count(*)
        from message m
        join chat_message_join cm on cm.message_id = m.ROWID
        where m.text like ? escape '\\' and cm.chat_id = ?
        """
        params.append(chat_rowid)
    total = con.execute(count_sql, params).fetchone()[0]
    if total > 500:
        return total, []
    sql = """
    select
      m.guid as guid,
      m.date as date,
      m.is_from_me as is_from_me,
      m.text as text,
      m.service as service,
      h.id as handle,
      c.guid as chat_guid,
      c.display_name as chat_name,
      c.service_name as chat_service,
      c.chat_identifier as chat_identifier
    from message m
    join chat_message_join cm on cm.message_id = m.ROWID
    join chat c on c.ROWID = cm.chat_id
    left join handle h on h.ROWID = m.handle_id
    where m.text like ? escape '\\'
    """
    qparams: list = [like]
    if chat_rowid is not None:
        sql += " and c.ROWID = ?"
        qparams.append(chat_rowid)
    sql += " order by m.date desc limit ?"
    qparams.append(limit)
    hits = []
    needle = query.casefold()
    for row in con.execute(sql, qparams):
        hits.append({
            "id": row["guid"],
            "at": apple_to_iso(row["date"]),
            "fromMe": bool(row["is_from_me"]),
            "handle": None if row["is_from_me"] else row["handle"],
            "service": row["service"] or row["chat_service"],
            "chatGuid": row["chat_guid"],
            "chatName": row["chat_name"] or None,
            "chatIdentifier": row["chat_identifier"],
            "snippet": _snippet(row["text"] or "", needle),
        })
    return total, hits


def _snippet(text: str, needle: str) -> str:
    flat = " ".join(text.split())
    idx = flat.casefold().find(needle)
    if idx < 0:
        return flat[:140]
    start = max(0, idx - 50)
    end = min(len(flat), idx + len(needle) + 90)
    chunk = flat[start:end]
    if start:
        chunk = "…" + chunk
    if end < len(flat):
        chunk = chunk + "…"
    return chunk
