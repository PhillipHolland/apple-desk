#!/usr/bin/env python3
"""Offline checks for the Notes markdown bridge. Does not call Notes.app."""
from __future__ import annotations

import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

LIB = Path(__file__).resolve().parents[1] / "lib"
sys.path.insert(0, str(LIB))

import cli  # noqa: E402
import markdown_notes  # noqa: E402

SAMPLE = Path(__file__).resolve().parent / "markdown-roundtrip-sample.md"

NOTES_HTML = """
<div><b><span style="font-size: 24px">Apple Desk markdown round-trip sample</span></b><br></div>
<div><b><span style="font-size: 18px">Lists</span></b><br></div>
<div>A paragraph with <b>bold</b> and <i>italic</i> and <u><a href="https://example.com/docs">a link</a></u>.</div>
<ul>
<li>alpha</li>
<li>beta</li>
</ul>
<div><br></div>
<ol>
<li>one</li>
<li>two</li>
</ol>
<div><font face="Courier"><tt>print("hello")</tt></font></div>
<div><font face="Courier"><tt>line two</tt></font></div>
<div><object><table cellspacing="0" cellpadding="0" style="border-collapse: collapse">
<tbody>
<tr><td><div>Col A</div></td><td><div>Col B</div></td></tr>
<tr><td><div>a</div></td><td><div>b</div></td></tr>
</tbody>
</table></object></div>
"""


def main():
    failures = []

    def check(name, cond):
        if cond:
            print("ok", name)
        else:
            failures.append(name)
            print("FAIL", name)

    text = SAMPLE.read_text(encoding="utf-8")
    converted = markdown_notes.markdown_to_notes_html(text)
    check("sample converts", converted.get("ok") is True)
    check("sample title", converted.get("title") == "Apple Desk markdown round-trip sample")
    html_text = converted.get("html") or ""
    check("h1 size", 'font-size: 24px' in html_text)
    check("h2 size", "font-size: 18px" in html_text)
    check("bullets", "<ul>" in html_text and "<li>alpha</li>" in html_text)
    check("numbers", "<ol>" in html_text and "<li>one</li>" in html_text)
    check("link", 'href="https://example.com/docs"' in html_text)
    warnings = " ".join(converted.get("warnings") or [])
    check("warn quote", "Block quotes" in warnings)
    check("warn footnote", "Footnotes" in warnings)
    check("warn image", "images" in warnings)
    check("warn nest", "Nested lists" in warnings)
    check("warn task", "Task markers" in warnings)
    check("warn depth", "three sizes" in warnings)
    check("warn code lang", "language" in warnings)

    back = markdown_notes.notes_html_to_markdown(html_text, title=converted["title"])
    src = markdown_notes.outline(text)
    out = markdown_notes.outline(back.get("markdown") or "")
    check("local h1", (1, "Apple Desk markdown round-trip sample") in out["headings"])
    check("local h2", (2, "Lists") in out["headings"])
    check("local h3", (3, "Numbered") in out["headings"])
    check("h4 collapsed", (4, "Deeper heading") in src["headings"] and (3, "Deeper heading") in out["headings"])
    for item in ("alpha", "beta", "gamma", "parent", "child"):
        check("bullet " + item, item in out["bullets"])
    for item in ("one", "two", "three"):
        check("number " + item, item in out["numbers"])
    check("local bold", "**bold**" in (back.get("markdown") or ""))
    check("local strike", "~~struck~~" in (back.get("markdown") or ""))
    check("local table", "| Col A | Col B |" in (back.get("markdown") or ""))
    check("local code", 'print("hello")' in (back.get("markdown") or ""))

    exported = markdown_notes.notes_html_to_markdown(NOTES_HTML)
    body = exported.get("markdown") or ""
    shaped = markdown_notes.outline(body)
    check("notes html h1", shaped["headings"][:1] == [(1, "Apple Desk markdown round-trip sample")])
    check("notes html h2", (2, "Lists") in shaped["headings"])
    check("notes html bullets", shaped["bullets"] == ["alpha", "beta"])
    check("notes html numbers", shaped["numbers"] == ["one", "two"])
    check("notes html link", "[a link](https://example.com/docs)" in body)
    check("notes html fence", 'print("hello")' in body and "line two" in body)
    check("notes html table", "| a | b |" in body)

    out_buf = io.StringIO()
    err_buf = io.StringIO()
    with redirect_stdout(out_buf), redirect_stderr(err_buf):
        code = cli.main(["import-md", str(SAMPLE), "--folder", "Notes"])
    check("dry-run exit", code == 0)
    check("dry-run text", "Notes.app was not called" in out_buf.getvalue())
    check("dry-run warns", "Block quotes" in err_buf.getvalue())
    help_text = cli.build_parser().format_help()
    check("help import", "import-md" in help_text)
    check("help export", "export-md" in help_text)
    check("version", cli.VERSION == "0.2.3")

    if failures:
        print("failures:", ", ".join(failures))
        return 1
    print("all ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
