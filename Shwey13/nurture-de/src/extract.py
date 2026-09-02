"""Task 4b — clean re-extraction for NurtureDE.

Reads the cached raw HTML in data/raw/{id}.html and writes clean Markdown to
data/processed/{id}.md, preserving heading hierarchy (h1-h3), lists, and
paragraph breaks — the structure the chunker will depend on. Then recomputes
content_hash from the CLEAN MARKDOWN and writes it back into sources.yaml.

Why this exists (see DAY1_LOG.md): the first extractor (fetch.py, stdlib
html.parser) collapsed all whitespace, destroying every heading and leaving the
Familienportal 7,080-char cookie/nav header inline. That processed text was
unusable for chunking. This pass replaces it.

Design:
  - beautifulsoup4 (html.parser backend, no lxml) so we can (a) select the main
    content container per domain, (b) DELETE nav/header/footer/widget subtrees,
    and (c) descend into TK's <tkds-*> custom elements — none of which a SAX
    stream or a heuristic extractor can do reliably. Selectors are explicit and
    auditable, which a provenance project needs.
  - No network. Operates purely on cached data/raw/. Safe to re-run.

Usage:
  py src/extract.py                 # extract every source, rewrite hashes
  py src/extract.py --only ID[,ID]  # just these ids
  py src/extract.py --dry-run       # write nothing; report what would happen
  py src/extract.py --stats         # after a run: before/after char counts + flags
"""

import argparse
import os
import re
import sys
from urllib.parse import urlsplit

from bs4 import BeautifulSoup, NavigableString, Tag

# Reuse fetch.py's paths, comment-safe YAML writeback, and text hasher (DRY).
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fetch import (  # noqa: E402
    SOURCES_PATH, RAW_DIR, PROCESSED_DIR,
    load_sources, save_lines, set_fields_for_id, sha256_text, decode_bytes,
)


# --------------------------------------------------------------------------- #
# Per-domain content selectors (the one place domain knowledge lives)
# --------------------------------------------------------------------------- #
# root(soup) -> the single element that holds the real article for that domain.
# Everything outside it (site nav, cookie modal, breadcrumb, footer) is simply
# not selected, which removes the bulk of each site's boilerplate for free.
DOMAIN_RULES = {
    # Familienportal: <main id="main">. The 7,080-char cookie/Matomo/nav header
    # and the 5 <nav> blocks live OUTSIDE <main>, so selecting it drops them.
    "familienportal.de": lambda s: s.find("main", id="main"),
    # gesund.bund.de: a single <article>; nav breadcrumb + emergency-number
    # footer are outside it.
    "gesund.bund.de":    lambda s: s.find("article"),
    # TK: <main id="tkde-maincontent">. Headings are <tkds-headline> custom
    # elements and content sits in <tkds-layout-section>/<tkds-accordion> — the
    # generic walker below descends into them because bs4 treats unknown tags
    # as ordinary nodes.
    "tk.de":             lambda s: s.find("main", id="tkde-maincontent"),
    # BMAS statute page: no <main id>, minimal structure. Fall back to <article>
    # then <main>, then <body>; this doc is essentially one prose blob.
    "bmas.de":           lambda s: (s.find("article") or s.find("main") or s.body),
    # gesetze-im-internet.de (BMJ/juris): no <main>/<article>. The statute title
    # (<h1 class="headline">) and Inhaltsübersicht table live in
    # <div id="container">; site nav (<div id="nav_2022">) and footer
    # (<div id="fusszeile">) are siblings outside it.
    "gesetze-im-internet.de": lambda s: s.find("div", id="container"),
}

# Tags whose entire subtree is chrome, deleted before extraction.
# NB: <button> and <header> are deliberately NOT here — within the selected
# content root they wrap real headings (gesund.bund.de nests section <h2>s in
# accordion <button>s and the article title <h1> in <header class="article-
# header">), so they are UNWRAPPED (see strip_boilerplate), not deleted. The
# site-level header/nav are already excluded by root selection.
DROP_TAGS = ["script", "style", "noscript", "svg", "template", "iframe",
             "form", "footer", "nav", "aside", "figure"]

# class/id substrings that mark a boilerplate widget even inside the main
# container (cookie stubs, "was this helpful?" feedback, breadcrumbs, teasers).
DROP_ATTR_PATTERNS = re.compile(
    r"cookie|consent|feedback|bewertung|rating|breadcrumb|contact-flap|"
    r"social|skip-link|sr-only|visually-hidden|teaser|related|meta-nav|"
    r"content-cluster|footer-links|__nav|nav-list|"
    r"header__buttons|bookmark|header-alert|"
    # P5 (Phase-2 finding): TK leaks a floating "Contact" button (div.contact-
    # button) and an article publish date (tkds-text.article-header__data-and-
    # author) into the content root — both surfaced at the head of embed_text.
    r"contact-button|data-and-author",
    re.I,
)

# ADJ 3 — post-extraction guard. The two-layer strip assumes the cookie/Matomo
# block always sits OUTSIDE the selected root. If it ever sits inside on even
# one page, that page silently keeps ~7,080 chars of analytics text. These
# strings must never survive into output; if one does, we fail loudly.
FORBIDDEN_STRINGS = ("Matomo", "Einwilligung zur Verwendung von Cookies")

# Heading phrases that are feedback/teaser chrome, dropped by exact-ish match.
DROP_HEADING_TEXT = re.compile(
    r"^(haben sie die gesuchten informationen|vielen dank für ihr feedback|"
    r"was this answer helpful|thank you for your feedback|"
    r"we are sorry that this article|most frequently asked|"
    r"zur gesamtausgabe der norm)",
    re.I,
)

# Corpus-validation lesson (Day 2): the BMAS "statute" page turned out to be a
# ~140-char referral stub. Any source whose CLEAN extraction is under this many
# chars is flagged as a probable stub / JS-rendered page needing manual review.
STUB_MIN_CHARS = 500

HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
SKIP_INLINE = {"script", "style", "noscript", "svg", "template"}

# Tags that count as "block-level content" when deciding whether a container
# should be recursed into (it has structure) or treated as a text leaf (emit
# its text directly). Includes TK's custom <tkds-headline>. This is what makes
# TK's <tkds-text> bodies (bare text, no <p>) get captured instead of dropped.
BLOCKISH = ["p", "ul", "ol", "table", "li",
            "h1", "h2", "h3", "h4", "h5", "h6", "tkds-headline"]


# --------------------------------------------------------------------------- #
# Cleaning
# --------------------------------------------------------------------------- #
def clean_text(s):
    """Collapse internal runs of whitespace WITHIN one block (never across)."""
    return re.sub(r"\s+", " ", s).strip()


def strip_boilerplate(root):
    """Delete chrome subtrees inside the selected root, in place."""
    for tag in DROP_TAGS:
        for el in root.find_all(tag):
            el.decompose()
    for el in root.find_all(attrs={"class": DROP_ATTR_PATTERNS}):
        el.decompose()
    for el in root.find_all(attrs={"id": DROP_ATTR_PATTERNS}):
        el.decompose()
    # <button> (accordion toggles wrapping <h2>) and <header> (article-header
    # wrapping the title <h1>) CONTAIN real headings — deleting them would
    # delete the headings, so unwrap: drop the wrapper, keep its contents. Junk
    # buttons (Merken/Vorlesen) hold only loose text the walker ignores;
    # cookie/consent/feedback wrappers were already removed by the filter above.
    for wrapper in root.find_all(["button", "header"]):
        wrapper.unwrap()


# --------------------------------------------------------------------------- #
# HTML subtree -> Markdown (heading-preserving)
# --------------------------------------------------------------------------- #
def _heading_level(el):
    """Markdown level for a heading node. Standard h1-h6, plus TK's custom
    <tkds-headline>, which (verified in the raw HTML) carries an explicit
    `level` attribute: level="1" title, "2" section, "3" subsection. Preserve
    that nesting rather than flattening. Fall back to class 'title' => h1 else
    h2 only if the attribute is absent (those cases are feedback/footer chrome
    that gets dropped anyway)."""
    name = el.name.lower()
    if name in HEADINGS:
        return int(name[1])
    if name == "tkds-headline":
        lvl = el.get("level")
        if lvl and lvl.isdigit():
            return max(1, min(int(lvl), 6))
        classes = " ".join(el.get("class", []))
        return 1 if "title" in classes else 2
    return None


def _is_heading(el):
    return el.name and (el.name.lower() in HEADINGS or el.name.lower() == "tkds-headline")


def _list_lines(list_el, ordered, depth):
    """Render a <ul>/<ol> to indented markdown lines, recursing into nested
    lists. Nested lists are extracted so a parent <li>'s text excludes them."""
    lines = []
    idx = 1
    for li in list_el.find_all("li", recursive=False):
        sublists = [c for c in li.find_all(["ul", "ol"], recursive=False)]
        for s in sublists:
            s.extract()  # remove before reading li's own text (soup is discarded after)
        txt = clean_text(li.get_text(" ", strip=True))
        bullet = ("%d." % idx) if ordered else "-"
        if txt:
            lines.append("%s%s %s" % ("  " * depth, bullet, txt))
        for s in sublists:
            lines.extend(_list_lines(s, s.name == "ol", depth + 1))
        idx += 1
    return lines


def _table_md(table_el):
    """Defensive pipe-table renderer (corpus currently has 0 tables)."""
    rows = []
    for tr in table_el.find_all("tr"):
        cells = [clean_text(c.get_text(" ", strip=True))
                 for c in tr.find_all(["th", "td"])]
        if cells:
            rows.append(cells)
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    out = ["| " + " | ".join(rows[0]) + " |",
           "| " + " | ".join(["---"] * width) + " |"]
    for r in rows[1:]:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def _emit_mixed(node, blocks):
    """P4 (Phase-2 finding): a <p> that wraps a block-level child — a <table>
    (often inside a <div>), <ul>, or <ol>. Familienportal ships <table> nested in
    <p>, which is invalid HTML; the plain <p> branch flattened it via get_text()
    into a number-wall and never reached _table_md. Walk children in document
    order, flushing buffered inline text as a paragraph before each block, so
    neither the surrounding sentences nor the table/list are lost."""
    buf = []

    def flush():
        if buf:
            txt = clean_text(" ".join(buf))
            if txt:
                blocks.append(txt)
            buf[:] = []

    for c in node.children:
        if isinstance(c, NavigableString):
            buf.append(str(c))
            continue
        name = c.name.lower()
        if name in SKIP_INLINE:
            continue
        if name == "table":
            flush()
            t = _table_md(c)
            if t:
                blocks.append(t)
        elif name in ("ul", "ol"):
            flush()
            lines = _list_lines(c, name == "ol", 0)
            if lines:
                blocks.append("\n".join(lines))
        elif c.find(["table", "ul", "ol"]) is not None:
            flush()
            _emit_mixed(c, blocks)          # e.g. the <div> that holds the tables
        else:
            buf.append(c.get_text(" ", strip=True))
    flush()


def collect_blocks(node, blocks):
    """Walk children in document order, emitting Markdown blocks. Each block is
    a string; blocks are later joined with blank lines. Lists/tables emit as a
    single multi-line block so their internal lines stay together."""
    for child in node.children:
        if not isinstance(child, Tag):
            continue  # loose text is captured via its parent block element
        name = child.name.lower()
        if name in SKIP_INLINE:
            continue
        if _is_heading(child):
            txt = clean_text(child.get_text(" ", strip=True))
            if not txt or DROP_HEADING_TEXT.match(txt):
                continue
            level = _heading_level(child) or 2
            blocks.append("#" * min(level, 6) + " " + txt)
        elif name == "p":
            if child.find(["table", "ul", "ol"]) is not None:
                _emit_mixed(child, blocks)      # P4: block nested inside a <p>
            else:
                txt = clean_text(child.get_text(" ", strip=True))
                if txt:
                    blocks.append(txt)
        elif name in ("ul", "ol"):
            lines = _list_lines(child, name == "ol", 0)
            if lines:
                blocks.append("\n".join(lines))
        elif name == "table":
            t = _table_md(child)
            if t:
                blocks.append(t)
        elif name in ("br", "hr", "img", "input"):
            continue
        elif child.find(BLOCKISH) is not None:
            # Structural container (div/section/article/tkds-layout-*) that
            # holds block-level descendants: recurse into it.
            collect_blocks(child, blocks)
        else:
            # Leaf container holding only text/inline content and no block
            # descendants (e.g. TK's <tkds-text>, whose body text is NOT
            # wrapped in <p>). Emit its text so nothing is silently dropped.
            txt = clean_text(child.get_text(" ", strip=True))
            if txt:
                blocks.append(txt)


def html_to_markdown(root):
    blocks = []
    collect_blocks(root, blocks)
    md = "\n\n".join(blocks)
    md = re.sub(r"\n{3,}", "\n\n", md).strip()
    return md + "\n" if md else ""


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #
def domain_of(url):
    return urlsplit(url).netloc.replace("www.", "")


def select_root(soup, domain):
    rule = DOMAIN_RULES.get(domain)
    return rule(soup) if rule else None


def extract_one(source):
    """Return (markdown, note) for one source, or (None, reason) on failure."""
    sid, url = source["id"], source["url"]
    raw_path = os.path.join(RAW_DIR, sid + ".html")
    if not os.path.exists(raw_path):
        return None, "no raw HTML (run fetch.py first)"
    # Decode by the page's OWN charset (header→<meta>→utf-8→latin-1), not a
    # hardcoded utf-8: gesetze-im-internet.de is ISO-8859-1, so a fixed utf-8
    # read mangles raw high bytes (e.g. the statute title "Müttern").
    with open(raw_path, "rb") as f:
        html = decode_bytes(f.read(), None)
    soup = BeautifulSoup(html, "html.parser")
    domain = domain_of(url)
    root = select_root(soup, domain)
    if root is None:
        return None, "content container not found for domain %s" % domain
    strip_boilerplate(root)
    md = html_to_markdown(root)
    if not md.strip():
        return None, "empty after extraction"
    return md, None


def parse_args():
    ap = argparse.ArgumentParser(description="NurtureDE clean re-extraction")
    ap.add_argument("--only", help="comma-separated ids")
    ap.add_argument("--dry-run", action="store_true", help="write nothing")
    ap.add_argument("--stats", action="store_true",
                    help="print before/after char counts + validation flags")
    return ap.parse_args()


def main():
    args = parse_args()
    os.makedirs(PROCESSED_DIR, exist_ok=True)
    sources, raw_lines = load_sources()
    only = {x.strip() for x in args.only.split(",")} if args.only else set()
    selected = [s for s in sources if not only or s["id"] in only]

    counts = {"ok": 0, "failed": 0, "changed": 0, "skipped": 0}
    failures, stub_ids, stats = [], [], []

    print("=" * 72)
    print("NurtureDE extract — %d source(s)%s" %
          (len(selected), " [DRY RUN]" if args.dry_run else ""))
    print("=" * 72)

    for s in selected:
        sid = s["id"]
        # Superseded entries are kept in sources.yaml for the record but are
        # NOT ingested — don't produce a processed artifact for them.
        if s.get("status") == "superseded":
            print("  [skip] %-32s superseded by %s (not ingested)"
                  % (sid, s.get("superseded_by") or "?"))
            counts["skipped"] += 1
            continue
        md, err = extract_one(s)
        if md is None:
            print("  [FAIL] %-32s %s" % (sid, err))
            counts["failed"] += 1
            failures.append(sid)
            continue

        # ADJ 3 — refuse to write a contaminated file; fail the whole run.
        leak = [needle for needle in FORBIDDEN_STRINGS if needle in md]
        if leak:
            print("  [LEAK] %-32s boilerplate survived root-selection: %s"
                  % (sid, ", ".join(leak)))
            counts["failed"] += 1
            failures.append(sid + " (boilerplate leak)")
            continue

        md_path = os.path.join(PROCESSED_DIR, sid + ".md")
        old_txt = os.path.join(PROCESSED_DIR, sid + ".txt")
        before = os.path.getsize(old_txt) if os.path.exists(old_txt) else 0
        after = len(md.encode("utf-8"))
        n_head = md.count("\n# ") + md.count("\n## ") + md.count("\n### ") + \
            (1 if md.startswith(("# ", "## ", "### ")) else 0)
        new_hash = sha256_text(md)
        stats.append((sid, before, after, md.count("\n") + 1, n_head))

        stub = after < STUB_MIN_CHARS
        if stub:
            stub_ids.append(sid)
        print("  [ok]   %-32s %6d -> %5d chars, %d headings%s" %
              (sid, before, after, n_head,
               "   <-- STUB? (<%d chars, review)" % STUB_MIN_CHARS if stub else ""))
        counts["ok"] += 1

        if not args.dry_run:
            with open(md_path, "w", encoding="utf-8", newline="\n") as f:
                f.write(md)
            if set_fields_for_id(raw_lines, sid, {"content_hash": new_hash}):
                counts["changed"] += 1

    if not args.dry_run:
        save_lines(raw_lines)

    print("\n" + "=" * 72)
    print("SUMMARY: ok=%(ok)d  skipped=%(skipped)d  failed=%(failed)d  "
          "hash-changed=%(changed)d" % counts)
    if failures:
        print("  failed: %s" % ", ".join(failures))
    if stub_ids:
        print("  STUB (<%d chars, manual review): %s"
              % (STUB_MIN_CHARS, ", ".join(stub_ids)))
    print("=" * 72)

    if args.stats:
        print("\nBEFORE/AFTER (chars) and validation flags")
        print("-" * 72)
        print("%-32s %8s %8s %7s  %s" %
              ("id", "before", "after", "%red", "flags"))
        for sid, before, after, nlines, nhead in sorted(stats):
            red = (100 * (before - after) / before) if before else 0
            flags = []
            if nlines <= 1:
                flags.append("NO-NEWLINES")
            if nhead == 0:
                flags.append("NO-HEADING")
            if after < STUB_MIN_CHARS:
                flags.append("STUB?")
            print("%-32s %8d %8d %6.1f%%  %s" %
                  (sid, before, after, red, " ".join(flags) or "ok"))

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
