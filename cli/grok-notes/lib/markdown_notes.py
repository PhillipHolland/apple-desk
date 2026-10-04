"""Markdown bridge for Notes.app.

File > Import Markdown and File > Export To > Markdown are not in the Notes
4.13 scripting dictionary, so this converts a Markdown subset to the HTML
Notes keeps and converts that HTML back. Heading sizes were probed on Notes
4.13: 24px bold, 18px bold, and plain bold. A smaller heading collapses to
plain bold. Nested lists come back flat.
"""
from __future__ import annotations

import html
import re
from html.parser import HTMLParser

HEAD_RE = re.compile(r"^(#{1,6})\s+(\S.*)$")
FENCE_RE = re.compile(r"^(\s{0,3})(`{3,}|~{3,})(.*)$")
HR_RE = re.compile(r"^(?:(?:-\s*){3,}|(?:\*\s*){3,}|(?:_\s*){3,})$")
LIST_RE = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
TASK_RE = re.compile(r"^\[([ xX])\]\s+(.*)$")
QUOTE_RE = re.compile(r"^\s{0,3}>\s?(.*)$")
FONT_SIZE_RE = re.compile(r"font-size:\s*(\d+(?:\.\d+)?)px", re.I)
SEP_CELL_RE = re.compile(r":?-{3,}:?")

_CELL = (
    'valign="top" style="border-style: solid; border-width: 1.0px 1.0px 1.0px 1.0px; '
    'border-color: #ccc; padding: 3.0px 5.0px 3.0px 5.0px; min-width: 70px"'
)
_VOID = {"br", "hr", "img", "meta", "link", "col"}


def markdown_to_notes_html(text, title=None, fallback_title=None):
    raw = (text or "").lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.strip():
        return {"ok": False, "error": "empty_markdown", "message": "The markdown file has no content."}
    blocks, warnings = _parse_blocks(raw.split("\n"))
    title, blocks, warnings = _apply_title(blocks, warnings, title, fallback_title)
    if not blocks:
        return {"ok": False, "error": "empty_markdown", "message": "The markdown file has no content."}
    parts = []
    for block in blocks:
        if parts:
            parts.append("<div><br></div>")
        parts.append(_render_md_block(block, warnings))
    return {
        "ok": True,
        "title": title,
        "html": "\n".join(parts),
        "warnings": warnings,
        "stats": _stats(blocks),
    }


def notes_html_to_markdown(html_text, title=None):
    warnings = []
    root = _parse_html(html_text or "")
    blocks = []
    code_run = []

    def flush_code():
        if not code_run:
            return
        body = "\n".join(code_run).rstrip("\n")
        blocks.append("```\n" + body + "\n```")
        code_run.clear()

    for child in root.children:
        if isinstance(child, str):
            if child.strip():
                flush_code()
                blocks.append(_escape_text(child.strip()))
            continue
        if _is_code_div(child):
            code_run.append(_code_line_text(child))
            continue
        flush_code()
        rendered = _render_html_block(child, warnings)
        if rendered:
            blocks.append(rendered)
    flush_code()
    if not blocks and title:
        blocks.append("# " + _escape_text(title))
        warnings.append("The note body was empty.")
    markdown = re.sub(r"\n{3,}", "\n\n", "\n\n".join(blocks).strip()) + ("\n" if blocks else "")
    return {
        "ok": True,
        "markdown": markdown,
        "warnings": _unique(warnings),
        "stats": _outline_stats(markdown),
    }


def outline(markdown):
    headings = []
    bullets = []
    numbers = []
    for line in (markdown or "").splitlines():
        stripped = line.strip()
        head = HEAD_RE.match(stripped)
        if head:
            headings.append((len(head.group(1)), head.group(2).strip()))
            continue
        item = LIST_RE.match(line)
        if not item or item.group(1):
            # Top-level items only. Indented items are nested and Notes flattens them.
            if item and item.group(1):
                text = item.group(3).strip()
                if re.match(r"\d", item.group(2)):
                    numbers.append(text)
                else:
                    bullets.append(text)
            continue
        text = item.group(3).strip()
        if re.match(r"\d", item.group(2)):
            numbers.append(text)
        else:
            bullets.append(text)
    return {"headings": headings, "bullets": bullets, "numbers": numbers}


def _apply_title(blocks, warnings, title, fallback_title):
    requested = (title or "").strip()
    first = blocks[0] if blocks else None
    if requested:
        plain = _plain_inline(requested)
        if first and first.get("type") == "heading" and first.get("level") == 1:
            if _plain_inline(first.get("text") or "") != plain:
                first["text"] = requested
                _warn(warnings, "title-override", "The first heading was replaced by --title.")
        else:
            blocks.insert(0, {"type": "heading", "level": 1, "text": requested})
        return plain or requested, blocks, warnings
    if first and first.get("type") == "heading" and first.get("level") == 1:
        plain = _plain_inline(first.get("text") or "")
        return plain or first.get("text") or "Untitled", blocks, warnings
    fallback = (fallback_title or "").strip() or "Untitled"
    blocks.insert(0, {"type": "heading", "level": 1, "text": fallback})
    _warn(warnings, "synthetic-title", "No top heading was in the file. The file name was used as the note title.")
    return fallback, blocks, warnings


def _parse_blocks(lines):
    blocks = []
    warnings = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        fence = FENCE_RE.match(line)
        if fence:
            block, i = _parse_fence(lines, i, fence, warnings)
            blocks.append(block)
            continue
        head = HEAD_RE.match(line.strip())
        if head:
            level = len(head.group(1))
            if level > 3:
                _warn(warnings, "heading-depth", "Headings past level 3 are stored as a bold subheading. Notes keeps three sizes.")
            blocks.append({"type": "heading", "level": level, "text": head.group(2).strip()})
            i += 1
            continue
        if HR_RE.match(line.strip()):
            blocks.append({"type": "hr"})
            i += 1
            continue
        if _table_starts(lines, i):
            block, i = _parse_table(lines, i, warnings)
            blocks.append(block)
            continue
        if QUOTE_RE.match(line):
            block, i = _parse_quote(lines, i, warnings)
            blocks.append(block)
            continue
        if LIST_RE.match(line):
            block, i = _parse_list(lines, i, warnings)
            blocks.append(block)
            continue
        para = [line.strip()]
        i += 1
        while i < n and lines[i].strip() and not _starts_block(lines, i):
            para.append(lines[i].strip())
            i += 1
        text = " ".join(para).strip()
        if text:
            if "[^" in text:
                _warn(warnings, "footnote", "Footnotes stay as literal text. Notes has no footnote object in this bridge.")
            blocks.append({"type": "p", "text": text})
    return blocks, warnings


def _starts_block(lines, i):
    line = lines[i]
    if FENCE_RE.match(line) or HEAD_RE.match(line.strip()) or HR_RE.match(line.strip()):
        return True
    if QUOTE_RE.match(line) or LIST_RE.match(line) or _table_starts(lines, i):
        return True
    return False


def _parse_fence(lines, i, fence, warnings):
    marker = fence.group(2)
    lang = (fence.group(3) or "").strip()
    if lang:
        _warn(warnings, "code-lang", "A code fence language is dropped. Notes keeps the lines as monospaced text.")
    char = marker[0]
    min_len = len(marker)
    body = []
    i += 1
    closed = False
    while i < len(lines):
        close = FENCE_RE.match(lines[i])
        if close and close.group(2)[0] == char and len(close.group(2)) >= min_len and not (close.group(3) or "").strip():
            closed = True
            i += 1
            break
        body.append(lines[i])
        i += 1
    if not closed:
        _warn(warnings, "code-unclosed", "A code fence was not closed. The rest of the file was treated as code.")
    return {"type": "code", "text": "\n".join(body)}, i


def _parse_quote(lines, i, warnings):
    _warn(warnings, "quote", "Block quotes are stored as paragraphs. Notes drops blockquote markup.")
    parts = []
    while i < len(lines):
        match = QUOTE_RE.match(lines[i])
        if not match:
            break
        parts.append(match.group(1).strip())
        i += 1
    return {"type": "quote", "text": " ".join(p for p in parts if p)}, i


def _parse_list(lines, i, warnings):
    first = LIST_RE.match(lines[i])
    base = _indent(first.group(1))
    ordered = first.group(2)[0].isdigit()
    items = []
    while i < len(lines):
        match = LIST_RE.match(lines[i])
        if not match:
            break
        indent = _indent(match.group(1))
        item_ordered = match.group(2)[0].isdigit()
        if indent > base:
            if not items:
                break
            child, i = _parse_list(lines, i, warnings)
            items[-1]["children"].append(child)
            _warn(warnings, "nested-list", "Nested lists are stored flat. Notes does not keep the indent.")
            continue
        if indent < base or item_ordered != ordered:
            break
        text = match.group(3).strip()
        if TASK_RE.match(text):
            _warn(warnings, "task", "Task markers are stored as list text. Notes does not make a checklist from Markdown.")
        items.append({"text": text, "children": []})
        i += 1
    return {"type": "list", "ordered": ordered, "items": items}, i


def _parse_table(lines, i, warnings):
    header = _split_row(lines[i])
    sep = _split_row(lines[i + 1])
    i += 2
    if any(":" in cell for cell in sep):
        _warn(warnings, "table-align", "Table alignment is dropped. Notes keeps the cell text only.")
    rows = []
    while i < len(lines) and "|" in lines[i] and lines[i].strip() and not HEAD_RE.match(lines[i].strip()):
        if LIST_RE.match(lines[i]) and not lines[i].strip().startswith("|"):
            break
        rows.append(_split_row(lines[i]))
        i += 1
    width = max([len(header)] + [len(row) for row in rows] or [1])
    header = _pad(header, width)
    rows = [_pad(row, width) for row in rows]
    if "[^" in " ".join(header + [cell for row in rows for cell in row]):
        _warn(warnings, "footnote", "Footnotes stay as literal text. Notes has no footnote object in this bridge.")
    return {"type": "table", "header": header, "rows": rows}, i


def _table_starts(lines, i):
    if i + 1 >= len(lines) or "|" not in lines[i]:
        return False
    cells = _split_row(lines[i + 1])
    return bool(cells) and all(SEP_CELL_RE.fullmatch(cell) for cell in cells)


def _split_row(line):
    text = line.strip()
    if text.startswith("|"):
        text = text[1:]
    if text.endswith("|") and not text.endswith("\\|"):
        text = text[:-1]
    cells = []
    buf = []
    escaped = False
    for ch in text:
        if escaped:
            buf.append(ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == "|":
            cells.append("".join(buf).strip())
            buf = []
        else:
            buf.append(ch)
    cells.append("".join(buf).strip())
    return cells


def _pad(row, width):
    row = list(row)
    while len(row) < width:
        row.append("")
    return row[:width]


def _indent(spaces):
    return len(spaces.replace("\t", "    "))


def _render_md_block(block, warnings):
    kind = block.get("type")
    if kind == "heading":
        return _heading_html(block.get("level") or 1, block.get("text") or "")
    if kind == "p":
        return "<div>" + _inline_html(block.get("text") or "", warnings) + "</div>"
    if kind == "quote":
        return "<blockquote><div>" + _inline_html(block.get("text") or "", warnings) + "</div></blockquote>"
    if kind == "hr":
        return "<div><hr></div>"
    if kind == "code":
        lines = (block.get("text") or "").split("\n")
        out = []
        for line in lines:
            inner = "<br>" if line == "" else html.escape(line)
            out.append('<div><font face="Courier"><tt>' + inner + "</tt></font></div>")
        return "\n".join(out)
    if kind == "list":
        return _list_html(block, warnings)
    if kind == "table":
        return _table_html(block, warnings)
    return "<div></div>"


def _heading_html(level, text):
    inner = _inline_html(text, None)
    if level <= 1:
        return '<div><b><span style="font-size: 24px">' + inner + "</span></b></div>"
    if level == 2:
        return '<div><b><span style="font-size: 18px">' + inner + "</span></b></div>"
    return "<div><b>" + inner + "</b></div>"


def _list_html(block, warnings):
    tag = "ol" if block.get("ordered") else "ul"
    items = []
    for item in block.get("items") or []:
        inner = _inline_html(item.get("text") or "", warnings)
        for child in item.get("children") or []:
            inner += _list_html(child, warnings)
        items.append("<li>" + inner + "</li>")
    return "<" + tag + ">\n" + "\n".join(items) + "\n</" + tag + ">"


def _table_html(block, warnings):
    rows = [block.get("header") or []] + list(block.get("rows") or [])
    trs = []
    for row in rows:
        cells = []
        for cell in row:
            inner = _inline_html(cell, warnings) if cell else "<br>"
            cells.append("<td " + _CELL + "><div>" + inner + "</div></td>")
        trs.append("<tr>" + "".join(cells) + "</tr>")
    return (
        '<div><object><table cellspacing="0" cellpadding="0" style="border-collapse: collapse"><tbody>'
        + "".join(trs)
        + "</tbody></table></object></div>"
    )


def _inline_html(text, warnings):
    if text is None:
        return ""
    out = []
    i = 0
    n = len(text)
    while i < n:
        if text[i] == "\\" and i + 1 < n:
            out.append(html.escape(text[i + 1]))
            i += 2
            continue
        matched = _match_inline(text, i, warnings)
        if matched is not None:
            piece, i = matched
            out.append(piece)
            continue
        out.append(html.escape(text[i]))
        i += 1
    return "".join(out)


def _match_inline(text, i, warnings):
    if text.startswith("![", i):
        image = re.match(r"!\[([^\]]*)\]\(([^)\s]+)\)", text[i:])
        if image:
            _warn(warnings, "image", "Markdown images are not Notes attachments. The address is kept as a link.")
            alt = _inline_html(image.group(1), warnings) or html.escape(image.group(2))
            href = html.escape(image.group(2), quote=True)
            return '<a href="' + href + '">' + alt + "</a>", i + image.end()
    if text.startswith("`", i):
        end = text.find("`", i + 1)
        if end > i + 1 and "\n" not in text[i + 1:end]:
            inner = html.escape(text[i + 1:end])
            return '<font face="Courier"><span style="font-size: 12px">' + inner + "</span></font>", end + 1
    if text.startswith("[", i):
        link = re.match(r"\[([^\]]+)\]\(([^)\s]+)\)", text[i:])
        if link:
            label = _inline_html(link.group(1), warnings)
            href = html.escape(link.group(2), quote=True)
            return '<a href="' + href + '">' + label + "</a>", i + link.end()
    for marker, open_tag, close_tag in (
        ("~~", "<strike>", "</strike>"),
        ("***", "<b><i>", "</i></b>"),
        ("**", "<b>", "</b>"),
        ("__", "<b>", "</b>"),
        ("*", "<i>", "</i>"),
    ):
        piece = _wrap_marker(text, i, marker, open_tag, close_tag, warnings)
        if piece is not None:
            return piece
    if text.startswith("_", i) and _boundary_before(text, i):
        piece = _wrap_marker(text, i, "_", "<i>", "</i>", warnings)
        if piece is not None:
            return piece
    return None


def _wrap_marker(text, i, marker, open_tag, close_tag, warnings):
    if not text.startswith(marker, i):
        return None
    if marker == "_" and not _boundary_before(text, i):
        return None
    rest = text[i + len(marker):]
    end = rest.find(marker)
    if end <= 0 or "\n" in rest[:end]:
        return None
    if marker == "_" and end < len(rest) and rest[end - 1].isalnum():
        return None
    inner = _inline_html(rest[:end], warnings)
    return open_tag + inner + close_tag, i + len(marker) + end + len(marker)


def _boundary_before(text, i):
    return i == 0 or not text[i - 1].isalnum()


def _plain_inline(text):
    rendered = _inline_html(text, None)
    return html.unescape(re.sub(r"<[^>]+>", "", rendered)).strip()


def _stats(blocks):
    counts = {
        "headings": 0,
        "bulletItems": 0,
        "orderedItems": 0,
        "nestedLists": 0,
        "tables": 0,
        "codeBlocks": 0,
        "quotes": 0,
    }

    def walk(block):
        kind = block.get("type")
        if kind == "heading":
            counts["headings"] += 1
        elif kind == "list":
            key = "orderedItems" if block.get("ordered") else "bulletItems"
            for item in block.get("items") or []:
                counts[key] += 1
                for child in item.get("children") or []:
                    counts["nestedLists"] += 1
                    walk(child)
        elif kind == "table":
            counts["tables"] += 1
        elif kind == "code":
            counts["codeBlocks"] += 1
        elif kind == "quote":
            counts["quotes"] += 1

    for block in blocks:
        walk(block)
    return counts


class _Node:
    def __init__(self, tag, attrs):
        self.tag = tag
        self.attrs = {str(k).lower(): v for k, v in attrs}
        self.children = []


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("root", [])
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        node = _Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in _VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(_Node(tag.lower(), attrs))

    def handle_endtag(self, tag):
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def _parse_html(html_text):
    builder = _Builder()
    try:
        builder.feed(html_text or "")
        builder.close()
    except Exception:
        return _Node("root", [])
    return builder.root


def _render_html_block(node, warnings):
    if node.tag in ("script", "style"):
        return ""
    if node.tag in ("ul", "ol"):
        return "\n".join(_render_list(node, node.tag == "ol", 0))
    if node.tag == "table":
        return _render_table(node)
    if node.tag == "hr":
        return "---"
    if node.tag == "blockquote":
        inner = _render_inline(node).strip()
        if not inner:
            return ""
        return "\n".join("> " + line if line else ">" for line in inner.splitlines())
    if node.tag == "object":
        table = _find_tag(node, "table")
        if table:
            return _render_table(table)
        _warn(warnings, "object", "An inline object was omitted. Drawings and scans are not in the markdown.")
        return ""
    if node.tag == "div":
        sig = _significant(node)
        if len(sig) == 1 and isinstance(sig[0], _Node) and sig[0].tag in ("ul", "ol", "table", "hr", "blockquote", "object"):
            return _render_html_block(sig[0], warnings)
        table = _find_tag(node, "table")
        if table and not _text_outside(node, table):
            return _render_table(table)
        if any(isinstance(child, _Node) and child.tag == "hr" for child in sig) and not _own_text(node):
            return "---"
        level = _heading_level(node)
        if level:
            text = _render_inline(_heading_body(node)).strip()
            if text:
                return ("#" * level) + " " + text
        text = _render_inline(node).strip()
        return text
    text = _render_inline(node).strip()
    return text


def _render_list(node, ordered, indent):
    lines = []
    number = 1
    for child in node.children:
        if isinstance(child, str):
            continue
        if child.tag == "li":
            prefix = (" " * indent) + (f"{number}. " if ordered else "- ")
            text = _render_inline(child, skip_lists=True).strip()
            if text:
                lines.append(prefix + text)
                number += 1
            for sub in child.children:
                if isinstance(sub, _Node) and sub.tag in ("ul", "ol"):
                    lines.extend(_render_list(sub, sub.tag == "ol", indent + 2))
        elif child.tag in ("ul", "ol"):
            lines.extend(_render_list(child, child.tag == "ol", indent + 2))
    return lines


def _render_table(table):
    rows = []
    for tr in _descendants(table, "tr"):
        cells = []
        for cell in tr.children:
            if isinstance(cell, _Node) and cell.tag in ("td", "th"):
                cells.append(_render_inline(cell).replace("\n", " ").replace("|", "\\|").strip())
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    rows = [_pad(row, width) for row in rows]

    def line(row):
        return "| " + " | ".join(cell if cell else " " for cell in row) + " |"

    out = [line(rows[0]), "| " + " | ".join("---" for _ in range(width)) + " |"]
    for row in rows[1:]:
        out.append(line(row))
    return "\n".join(out)


def _render_inline(node, skip_lists=False):
    parts = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(_escape_text(child.replace("\u00a0", " ").replace("\ufffc", "")))
            continue
        if child.tag in ("script", "style"):
            continue
        if skip_lists and child.tag in ("ul", "ol"):
            continue
        if child.tag == "br":
            parts.append("\n")
            continue
        if child.tag in ("b", "strong"):
            inner = _render_inline(child, skip_lists=skip_lists).strip()
            if inner:
                parts.append("**" + inner + "**")
            continue
        if child.tag in ("i", "em"):
            inner = _render_inline(child, skip_lists=skip_lists).strip()
            if inner:
                parts.append("*" + inner + "*")
            continue
        if child.tag in ("strike", "s", "del"):
            inner = _render_inline(child, skip_lists=skip_lists).strip()
            if inner:
                parts.append("~~" + inner + "~~")
            continue
        if child.tag == "a":
            href = child.attrs.get("href") or ""
            label = _render_inline(child, skip_lists=skip_lists).strip() or href
            if href:
                parts.append("[" + label + "](" + href + ")")
            else:
                parts.append(label)
            continue
        if _is_mono_tag(child) and _element_text_is_mono(child):
            code = _raw_text(child).replace("\n", " ").strip()
            if code:
                parts.append("`" + code.replace("`", "'") + "`")
            continue
        parts.append(_render_inline(child, skip_lists=skip_lists))
    text = "".join(parts)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip() if text.strip() == text.strip(" \t") else text


def _heading_level(node):
    sig = [child for child in _significant(node) if not (isinstance(child, _Node) and child.tag == "br")]
    if len(sig) != 1 or not isinstance(sig[0], _Node) or sig[0].tag not in ("b", "strong", "h1", "h2", "h3", "h4", "h5", "h6"):
        only = _only_heading_tag(node)
        if only:
            return int(only.tag[1])
        return None
    tag = sig[0].tag
    if tag.startswith("h") and len(tag) == 2:
        return int(tag[1])
    size = _font_size(sig[0])
    if size is None:
        size = _font_size(node)
    if size is not None and size >= 22:
        return 1
    if size is not None and size >= 17:
        return 2
    return 3


def _only_heading_tag(node):
    found = [child for child in _significant(node) if isinstance(child, _Node) and child.tag in ("h1", "h2", "h3", "h4", "h5", "h6")]
    if len(found) == 1 and len(_significant(node)) == 1:
        return found[0]
    return None


def _heading_body(node):
    sig = _significant(node)
    if sig and isinstance(sig[0], _Node) and sig[0].tag in ("b", "strong"):
        return sig[0]
    return node


def _font_size(node):
    style = node.attrs.get("style") or ""
    match = FONT_SIZE_RE.search(style)
    if match:
        return float(match.group(1))
    for child in node.children:
        if isinstance(child, _Node):
            found = _font_size(child)
            if found is not None:
                return found
    return None


def _is_code_div(node):
    if not isinstance(node, _Node) or node.tag != "div":
        return False
    if _heading_level(node):
        return False
    saw_text = False
    for text, ancestors in _iter_text(node, []):
        if not text.strip():
            continue
        saw_text = True
        if not any(_is_mono_tag(ancestor) for ancestor in ancestors):
            return False
    if saw_text:
        return True
    return _has_mono_break(node)


def _has_mono_break(node):
    if _is_mono_tag(node):
        for child in node.children:
            if isinstance(child, _Node) and child.tag == "br":
                return True
    for child in node.children:
        if isinstance(child, _Node) and _has_mono_break(child):
            return True
    return False


def _code_line_text(node):
    parts = []
    for text, _ancestors in _iter_text(node, []):
        parts.append(text.replace("\u00a0", " ").replace("\ufffc", ""))
    if parts:
        return "".join(parts).replace("\n", "")
    return ""


def _is_mono_tag(node):
    if node.tag in ("tt", "code", "pre"):
        return True
    blob = ((node.attrs.get("face") or "") + " " + (node.attrs.get("style") or "")).lower()
    return any(token in blob for token in ("courier", "menlo", "monaco", "monospace", "ui-monospace"))


def _element_text_is_mono(node):
    saw = False
    for text, ancestors in _iter_text(node, []):
        if not text.strip():
            continue
        saw = True
        if not any(_is_mono_tag(ancestor) for ancestor in ancestors) and not _is_mono_tag(node):
            return False
    return saw


def _iter_text(node, ancestors):
    for child in node.children:
        if isinstance(child, str):
            yield child, ancestors
        else:
            yield from _iter_text(child, ancestors + [child])


def _significant(node):
    out = []
    for child in node.children:
        if isinstance(child, str):
            if child.strip():
                out.append(child)
        elif child.tag == "br":
            continue
        else:
            out.append(child)
    return out


def _own_text(node):
    return "".join(child.strip() for child in node.children if isinstance(child, str)).strip()


def _find_tag(node, tag):
    if node.tag == tag:
        return node
    for child in node.children:
        if isinstance(child, _Node):
            found = _find_tag(child, tag)
            if found:
                return found
    return None


def _descendants(node, tag):
    found = []
    for child in node.children:
        if not isinstance(child, _Node):
            continue
        if child.tag == tag:
            found.append(child)
        else:
            found.extend(_descendants(child, tag))
    return found


def _text_outside(node, skip):
    if node is skip:
        return ""
    parts = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        elif child is not skip:
            parts.append(_text_outside(child, skip))
    return "".join(parts).strip()


def _raw_text(node):
    parts = []
    for child in node.children:
        if isinstance(child, str):
            parts.append(child)
        else:
            parts.append(_raw_text(child))
    return "".join(parts)


def _escape_text(text):
    text = text.replace("\\", "\\\\")
    for char in ("*", "_", "`"):
        text = text.replace(char, "\\" + char)
    return text


def _warn(warnings, code, message):
    if warnings is None:
        return
    if any(item.startswith(code + ":") or item == message for item in warnings):
        return
    warnings.append(message)


def _unique(items):
    out = []
    for item in items:
        if item not in out:
            out.append(item)
    return out


def _outline_stats(markdown):
    data = outline(markdown)
    return {
        "headings": len(data["headings"]),
        "bulletItems": len(data["bullets"]),
        "orderedItems": len(data["numbers"]),
    }
