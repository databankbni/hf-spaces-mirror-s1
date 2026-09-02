# ADPC-stats

A static Hugging Face Space arguing the case for public pickleball courts in Abu
Dhabi from the Abu Dhabi Pickleball Club's own WhatsApp history.

- `index.html` — the argument: three pieces of evidence, then the ask. Self-contained;
  inline CSS and hand-rolled SVG charts, no dependencies.
- `stats.html` — the fuller group analysis it links to.
- `analysis/extract.py` — derives every figure on the page from the export.
- `data/` — the export. **Untracked, and it stays that way.**

Deploying, and the numbers behind the charts: see `.claude/skills/adpc-space`.

## The data rule

`data/` holds the raw WhatsApp export: real names, phone numbers, and sixteen
months of a private group's conversation. It is gitignored. Never commit it,
never paste its contents into the page, and never quote an identifiable member.
Only aggregates reach `index.html`.

The Space is public, so anything committed here is published.

## House style for the page

Charts are written by hand into `<svg>` elements from arrays declared at the top
of the script block — no chart library, and data arrays are the only thing that
should need editing when figures change. Two rules that came out of review:

- **Bigger means better.** A reader should never have to invert a chart to read
  it as good news. Growth is a rising line or a taller bar; "faster" is never a
  shorter bar.
- **Define the term, then use it.** Every count on the page names what it counts
  ("a scheduling poll posted in the group", not "demand") and says what it misses.
  Where a proxy breaks down, the page says so in the panel rather than in a
  footnote.
