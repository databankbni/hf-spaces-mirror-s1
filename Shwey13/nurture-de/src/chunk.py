#!/usr/bin/env python3
"""Phase 2 — heading-aware chunker for the NurtureDE corpus.

Segments each clean data/processed/*.md into retrievable chunks using
QUESTION-ANCHORED sectioning (Phase-2 finding): Familienportal encodes hierarchy
by convention, not markup — every heading is <h2>, a trailing '?' means a new
topic, a statement heading means a sub-part of the question above. So we anchor:

  * a question-h2 (text ends '?') opens a Q&A section and ABSORBS every following
    non-question h2/h3 as its sub-parts, until the next question-h2  -> no-merge
  * a run of non-question h2s with no open question = prose sections -> may merge
    adjacent small ones up to the token floor

Tokens are counted with cl100k (pure-Python reimpl, exact tiktoken parity — see
scratchpad/cl100k.py; tiktoken has no Py3.7 wheel). Targets: 250 floor / 500
target / 800 hard cap (heuristics; a multilingual tokenizer shifts German counts
~15-20%, which the headroom absorbs). Output: data/chunks.jsonl (git-ignored).
"""
import argparse
import hashlib
import io
import json
import os
import re
import statistics
import sys

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROC = os.path.join(ROOT, "data", "processed")
SOURCES = os.path.join(ROOT, "data", "sources.yaml")
OUT = os.path.join(ROOT, "data", "chunks.jsonl")

# cl100k encoder + vocab are vendored in-repo (src/vendor) so the tracked
# chunks.jsonl is reproducible offline (PM-5). No external/Temp path.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vendor import cl100k  # noqa: E402

TOKENIZER = "cl100k_base"
FLOOR, TARGET, CAP = 250, 500, 800

# --- E5 embedding-tokenizer cap ---------------------------------------------
# The chunker sizes structure in cl100k (a proxy), but the corpus is embedded
# with multilingual-e5-large, which TRUNCATES at 512 tokens. A proxy tokenizer
# cannot bound the real one (register P7): for the longest German chunks cl100k
# UNDERcounts vs E5 (max cl100k 791 vs E5 906), the unsafe direction. So after
# the cl100k cascade we re-split any chunk whose *full embedded string*
# ("passage: " + heading breadcrumb + text) exceeds E5_SAFE, measured with the
# actual E5 tokenizer. E5_SAFE leaves a margin under 512 for special tokens.
E5_MODEL = "intfloat/multilingual-e5-large"
E5_HARD, E5_SAFE = 512, 500
E5_PASSAGE_PREFIX = "passage: "  # must match src/retrieval.py PASSAGE_PREFIX
_e5_tok = None


def e5_tok():
    """Lazy singleton — loads the E5 *tokenizer only* (no 2.2GB model weights)."""
    global _e5_tok
    if _e5_tok is None:
        from transformers import AutoTokenizer
        _e5_tok = AutoTokenizer.from_pretrained(E5_MODEL)
    return _e5_tok


def e5_count(embed_text):
    """E5 token length of exactly what the model sees at index time:
    PASSAGE_PREFIX + embed_text (embed_text already carries the heading prefix)."""
    return len(e5_tok()(E5_PASSAGE_PREFIX + embed_text, add_special_tokens=True)["input_ids"])


def _e5_over(prefix, text):
    """True if this chunk's full embedded string would truncate under E5_SAFE."""
    return e5_count(prefix + "\n" + text) > E5_SAFE


def _e5_units(prefix, text):
    """Break text into packing units, each <= E5_SAFE embedded. Paragraphs stay
    whole; a paragraph over the cap is sentence-packed (sentences joined by ' ')."""
    units = []
    for para in re.split(r"\n{2,}", text):
        para = para.strip()
        if not para:
            continue
        if not _e5_over(prefix, para):
            units.append(para)
            continue
        cur = ""
        for sent in re.split(r"(?<=[.!?])\s+", para):
            sent = sent.strip()
            if not sent:
                continue
            cand = sent if not cur else cur + " " + sent
            if cur and _e5_over(prefix, cand):
                units.append(cur)
                cur = sent
            else:
                cur = cand
        if cur:
            units.append(cur)
    return units


def _split_to_e5(prefix, text):
    """Re-split one over-budget chunk into BALANCED pieces, each within E5_SAFE.
    n = ceil(total/E5_SAFE) pieces, packed toward total/n so no tiny sub-floor tail
    is created (a 524-token chunk -> ~262/262, never 500/24)."""
    units = _e5_units(prefix, text)
    total = e5_count(prefix + "\n" + text)
    n = max(2, -(-total // E5_SAFE))     # integer ceil
    target = total / n
    pieces, cur = [], ""
    for u in units:
        cand = u if not cur else cur + "\n\n" + u
        hit_cap = _e5_over(prefix, cand)
        at_target = cur and e5_count(prefix + "\n" + cur) >= target
        if cur and (hit_cap or at_target):
            pieces.append(cur)
            cur = u
        else:
            cur = cand
    if cur:
        pieces.append(cur)
    return pieces


def enforce_e5_cap(texts, prefix):
    """Final pass after the cl100k cascade: guarantee every chunk fits E5's 512-token
    limit, measured on the FULL embedded string (passage prefix + heading breadcrumb +
    text). Chunks already within budget pass through byte-identical."""
    out = []
    for text in texts:
        if _e5_over(prefix, text):
            out.extend(_split_to_e5(prefix, text))
        else:
            out.append(text)
    return out

# Hub/index pages: mostly link lists, tagged so retrieval can down-weight rather
# than drop (they still answer "where do I apply for X"). Identified in Day-2 journal.
INDEX_SOURCES = {
    "fam_kindergeld", "fam_elterngeld",
    "fam_leistungen_ueberblick", "fam_staatliche_leistungen",
}

GUARD1_CEILING = 12   # canary, not a gate (see Phase-2 journal): flags a shift in
                      # the absorption distribution, which signals an upstream change.

HEAD = re.compile(r"^(#{1,6})\s+(.*)$")
ZW = "\u200b\u200c\u200d\ufeff"
UMLAUT = {"\u00e4": "ae", "\u00f6": "oe", "\u00fc": "ue", "\u00c4": "ae", "\u00d6": "oe", "\u00dc": "ue", "\u00df": "ss"}


def norm_heading(t):
    return t.strip().strip(ZW).strip()


def is_question(t):
    return norm_heading(t).endswith("?")


def toks(s):
    return cl100k.count(s)


def sha8(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:8]


def slugify(t):
    if not t:
        return "section"
    s = norm_heading(t)
    for k, v in UMLAUT.items():
        s = s.replace(k, v)
    s = re.sub(r"[^a-z0-9]+", "-", s.lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s[:60] or "section"


def render_members(members):
    parts = []
    for m in members:
        if m["level"]:
            parts.append("#" * m["level"] + " " + m["heading"])
        if m["body"]:
            parts.append(m["body"])
    return "\n\n".join(parts).strip()


def body_only(text):
    """text with heading lines removed \u2014 empty => orphan/echo heading."""
    return "\n".join(ln for ln in text.split("\n") if not HEAD.match(ln)).strip()


def doc_question_ratio(md):
    h2 = [norm_heading(HEAD.match(ln).group(2)) for ln in md.split("\n")
          if HEAD.match(ln) and len(HEAD.match(ln).group(1)) == 2]
    if not h2:
        return 0.0
    return sum(1 for h in h2 if h.endswith("?")) / len(h2)


def word_count(text):
    return len(re.findall(r"\w+", body_only(text), flags=re.UNICODE))


EURO = re.compile(r"\d[\d.,]*\s*Euro")


def is_table_degraded(text):
    """A run-on number-wall: a single-line, non-list paragraph dense with currency
    amounts and NO markdown-table structure. Phase-1b's P4 fix recovered every
    <p>-nested <table> into a proper pipe table, so this now flags only content the
    SOURCE itself wrote as an unstructured number run (e.g. a worked example in
    prose, not a <table>) — a benefit-amount hallucination hazard tagged for Day-3
    down-weight. Excludes rendered pipe tables (contain '|') and multi-line blocks."""
    for para in re.split(r"\n{2,}", body_only(text)):
        p = para.strip()
        if not p or p[:1] in ("-", "*") or "|" in p or "\n" in p:
            continue
        if len(EURO.findall(p)) >= 5:
            return True
    return False


def _glue_colon(units):
    """Keep lead-ins attached to what they introduce, so no chunk opens on a
    dangling fragment. Two rules (up to the cap):
      * forward — a unit ending ':' absorbs its successor (fixes thin intros);
      * backward — a unit that STARTS with a list marker is pulled into its
        predecessor (a bare list must never begin a chunk, colon or not)."""
    out, i = [], 0
    while i < len(units):
        u = units[i]
        while i + 1 < len(units) and toks(u + "\n\n" + units[i + 1]) <= CAP and (
                u.rstrip().endswith(":") or units[i + 1].lstrip()[:2] in ("- ", "* ")):
            i += 1
            u = u + "\n\n" + units[i]
        out.append(u)
        i += 1
    return out


# ---------------------------------------------------------------- parse -------
def parse_segments(md):
    """-> (h1, preamble_text, [ {level, heading, body} ])   (body incl. sub-lines)."""
    h1 = None
    seen_h1 = False
    preamble = []
    segs = []
    cur = None
    for ln in md.split("\n"):
        m = HEAD.match(ln)
        if m:
            lvl = len(m.group(1))
            txt = norm_heading(m.group(2))
            if lvl == 1 and not seen_h1:
                h1, seen_h1 = txt, True
                continue
            if lvl == 1:            # stray 2nd h1 -> treat as section heading
                lvl = 2
            cur = {"level": lvl, "heading": txt, "body": []}
            segs.append(cur)
        else:
            (cur["body"] if cur is not None else preamble).append(ln)
    for s in segs:
        s["body"] = "\n".join(s["body"]).strip()
    return h1, "\n".join(preamble).strip(), segs


# ------------------------------------------------------ anchored sections -----
def anchored_sections(md):
    """-> list of sections: {kind, root_heading, members:[seg], absorbed:int}.
    members[0] is the root; members[1:] are absorbed sub-parts."""
    h1, preamble, segs = parse_segments(md)
    sections = []
    if preamble:
        sections.append({"kind": "preamble", "root_heading": None,
                         "members": [{"level": 0, "heading": None, "body": preamble}],
                         "absorbed": 0})
    cur = None
    for s in segs:
        if s["level"] == 2 and is_question(s["heading"]):
            cur = {"kind": "qa", "root_heading": s["heading"], "members": [s], "absorbed": 0}
            sections.append(cur)
        elif s["level"] == 2:
            if cur is not None and cur["kind"] == "qa":
                cur["members"].append(s)          # absorb into open question
                cur["absorbed"] += 1
            else:
                cur = {"kind": "prose", "root_heading": s["heading"], "members": [s], "absorbed": 0}
                sections.append(cur)
        else:                                     # h3+ : attach to current
            if cur is not None:
                cur["members"].append(s)
                if cur["kind"] == "qa":
                    cur["absorbed"] += 1
            else:
                cur = {"kind": "prose", "root_heading": s["heading"], "members": [s], "absorbed": 0}
                sections.append(cur)
    return h1, sections


def section_text(sec):
    return render_members(sec["members"])


# ---------------------------------------------------- overflow split cascade --
def _pack(units, joiner):
    """Greedy-pack pre-sized text units toward TARGET (never mid-unit)."""
    out, cur, ct = [], [], 0
    for u in units:
        ut = toks(u)
        if cur and ct + ut > TARGET:
            out.append(joiner.join(cur))
            cur, ct = [u], ut
        else:
            cur.append(u)
            ct += ut
    if cur:
        out.append(joiner.join(cur))
    return out


def _split_block(text):
    """A single member over the cap: paragraph -> sentence."""
    paras = [p for p in re.split(r"\n{2,}", text) if p.strip()]
    units = []
    for p in paras:
        if toks(p) > CAP:
            units.extend(_pack(re.split(r"(?<=[.!?])\s+", p), " "))
        else:
            units.append(p)
    return _pack(_glue_colon(units), "\n\n")


def split_texts(members):
    """PRIMARY cascade: absorbed sub-part headings -> paragraph -> sentence."""
    full = render_members(members)
    if toks(full) <= CAP:
        return [full]
    mtexts = _glue_colon([t for t in (render_members([m]) for m in members) if t])
    out, cur, ct = [], [], 0
    for mt in mtexts:
        mtok = toks(mt)
        if mtok > CAP:                       # single member too big -> deeper split
            if cur:
                out.append("\n\n".join(cur))
                cur, ct = [], 0
            out.extend(_split_block(mt))
        elif cur and ct + mtok > TARGET:
            out.append("\n\n".join(cur))
            cur, ct = [mt], mtok
        else:
            cur.append(mt)
            ct += mtok
    if cur:
        out.append("\n\n".join(cur))
    # thin-root absorption: a section root whose own body is < floor must not
    # stand alone as a dangling stub — fold it into the first real sub-chunk.
    if len(out) > 1 and toks(out[0]) < FLOOR and toks(out[0] + "\n\n" + out[1]) <= CAP:
        out = [out[0] + "\n\n" + out[1]] + out[2:]
    return out


# ------------------------------------------------- logical units (merge pass) -
def logical_units(md):
    """Anchored sections -> logical units. Q&A never merge; adjacent prose merge
    toward the floor. Returns (h1, [unit]) where unit carries members for splitting."""
    h1, sections = anchored_sections(md)
    units = []
    buf = []          # accumulating prose/preamble sections

    def flush():
        if not buf:
            return
        members = [m for s in buf for m in s["members"]]
        units.append({"kind": "prose", "root_heading": buf[0]["root_heading"],
                      "members": members, "n_merged": len(buf),
                      "merge_policy": "prose_merge"})
        buf.clear()

    for sec in sections:
        if sec["kind"] == "qa":
            flush()
            units.append({"kind": "qa", "root_heading": sec["root_heading"],
                          "members": sec["members"], "n_merged": 1,
                          "merge_policy": "qa_no_merge"})
        else:                                # prose / preamble
            buf.append(sec)
            if toks(render_members([m for s in buf for m in s["members"]])) >= TARGET:
                flush()
    flush()
    return h1, units


# ------------------------------------------------------------- build chunks ---
def build_chunks(source, md):
    sid = source["id"]
    authority = source["authority"]
    h1, units = logical_units(md)
    qratio = round(doc_question_ratio(md), 3)
    kind_override = "index" if sid in INDEX_SOURCES else None
    recs = []
    for u in units:
        root = u["root_heading"]
        slug = slugify(root or h1)
        full = render_members(u["members"])
        parent_id = "%s__%s__%s" % (sid, slug, sha8(full))
        hp = [authority, h1] + ([root] if root else [])
        prefix = "[" + " › ".join(hp) + "]"
        base_kind = kind_override or ("qa" if u["kind"] == "qa" else "prose")
        for text in enforce_e5_cap(split_texts(u["members"]), prefix):
            content_kind = "table-degraded" if is_table_degraded(text) else base_kind
            chunk_id = "%s__%s__%s" % (sid, slug, sha8(text))
            recs.append({
                "chunk_id": chunk_id,
                "parent_section_id": parent_id,
                "source_id": sid,
                "url": source.get("url"),
                "authority": authority,
                "authority_tier": source.get("authority_tier"),
                "language": source.get("language"),
                "last_verified_date": source.get("last_verified_date"),
                "topic": source.get("topic"),
                "subtopic": source.get("subtopic"),
                "user_type": source.get("user_type"),
                "insurance_type": source.get("insurance_type"),
                "content_kind": content_kind,
                "merge_policy": u["merge_policy"],
                "n_merged": u["n_merged"],
                "question_ratio": qratio,
                "heading_path": hp,
                "section_slug": slug,
                "token_count": toks(text),
                "e5_token_count": e5_count(prefix + "\n" + text),
                "char_count": len(text),
                "tokenizer": TOKENIZER,
                "text": text,
                "embed_text": prefix + "\n" + text,
            })
    return recs


def dedupe(recs):
    """Drop orphan/echo headings (no body), sub-5-word boilerplate (footers,
    dates), and exact-duplicate bodies."""
    empties = thins = dups = 0
    seen = set()
    out = []
    for r in recs:
        if not body_only(r["text"]):
            empties += 1
            continue
        if word_count(r["text"]) < 5:
            thins += 1
            continue
        key = r["text"].strip()
        if key in seen:
            dups += 1
            continue
        seen.add(key)
        out.append(r)
    return out, empties, thins, dups


def load_active():
    d = yaml.safe_load(open(SOURCES, encoding="utf-8"))
    srcs = d["sources"] if isinstance(d, dict) and "sources" in d else d
    return [s for s in srcs if s.get("status") != "superseded"]


# --------------------------------------------------------------- guards -------
def run_guards():
    out = sys.stdout
    active = load_active()
    all_absorb = []           # absorption counts for qa sections
    over_cap = 0
    total_sections = 0
    flagged = []              # (id, heading, absorbed)
    zeroq = {"tk_maternity_benefits": None, "fam_kindergeld": None}
    persec_over = []
    for s in sorted(active, key=lambda x: x["id"]):
        md = open(os.path.join(PROC, s["id"] + ".md"), encoding="utf-8").read()
        h1, secs = anchored_sections(md)
        n_qa = sum(1 for x in secs if x["kind"] == "qa")
        n_prose = sum(1 for x in secs if x["kind"] in ("prose", "preamble"))
        for sec in secs:
            total_sections += 1
            t = toks(section_text(sec))
            if t > CAP:
                over_cap += 1
                persec_over.append((s["id"], sec["kind"], sec["root_heading"], t))
            if sec["kind"] == "qa":
                all_absorb.append(sec["absorbed"])
                if sec["absorbed"] > GUARD1_CEILING:
                    flagged.append((s["id"], sec["root_heading"], sec["absorbed"], t))
        if s["id"] in zeroq:
            zeroq[s["id"]] = (n_qa, n_prose, len(secs))

    print("=" * 76, file=out)
    print("GUARD 1 — absorption run distribution (per Q&A-anchored section)", file=out)
    print("=" * 76, file=out)
    if all_absorb:
        a = sorted(all_absorb)
        print("  qa sections: %d   absorbed h2/h3 -> min=%d median=%d mean=%.1f max=%d"
              % (len(a), a[0], int(statistics.median(a)), statistics.mean(a), a[-1]), file=out)
        from collections import Counter
        print("  distribution:", dict(sorted(Counter(a).items())), file=out)
        print("  sections absorbing >5:", len(flagged), file=out)
        for fid, h, n, t in flagged:
            print("     [>5] %-28s absorbed=%d tokens=%d  | %s" % (fid, n, t, (h or "")[:48]), file=out)
    else:
        print("  no qa sections found (unexpected)", file=out)

    print(file=out)
    print("=" * 76, file=out)
    print("GUARD 2 — zero-question documents fall entirely to prose", file=out)
    print("=" * 76, file=out)
    for zid, v in zeroq.items():
        if v is None:
            print("  %-26s NOT FOUND" % zid, file=out)
        else:
            nqa, npr, tot = v
            ok = "OK" if nqa == 0 else "FAIL"
            print("  %-26s qa_sections=%d prose_sections=%d total=%d  [%s]"
                  % (zid, nqa, npr, tot, ok), file=out)

    print(file=out)
    print("=" * 76, file=out)
    print("GUARD 3 — post-anchoring split rate (sections over the 800 cap)", file=out)
    print("=" * 76, file=out)
    rate = 100.0 * over_cap / total_sections
    print("  sections: %d   over cap: %d   split rate: %.1f%%  (pre-anchoring was 7.5%%)"
          % (total_sections, over_cap, rate), file=out)
    for fid, kind, h, t in sorted(persec_over, key=lambda x: -x[3])[:12]:
        print("     [>800] %-28s %-7s %5d tok | %s" % (fid, kind, t, (h or "")[:44]), file=out)

    g1 = len(flagged) == 0
    g2 = all(v is not None and v[0] == 0 for v in zeroq.values())
    g3 = rate <= 25.0
    print(file=out)
    print("VERDICT  guard1(no >5)=%s  guard2(zeroq prose)=%s  guard3(<=25%%)=%s"
          % (g1, g2, g3), file=out)
    print("ALL GUARDS PASS" if (g1 and g2 and g3) else "GUARD TRIPPED — STOP", file=out)
    return g1 and g2 and g3


def _stats(vals):
    a = sorted(vals)
    n = len(a)
    def p(q):
        return a[min(n - 1, int(q / 100 * n))]
    return dict(min=a[0], p25=p(25), median=p(50), p75=p(75), p90=p(90), max=a[-1])


def build_all():
    active = load_active()
    all_recs = []
    per_doc = {}
    absorb = []
    for s in sorted(active, key=lambda x: x["id"]):
        md = open(os.path.join(PROC, s["id"] + ".md"), encoding="utf-8").read()
        _, secs = anchored_sections(md)
        absorb += [x["absorbed"] for x in secs if x["kind"] == "qa"]
        recs = build_chunks(s, md)
        per_doc[s["id"]] = recs
        all_recs += recs
    return active, all_recs, per_doc, absorb


def write_and_report():
    out = sys.stdout
    active, recs, per_doc, absorb = build_all()

    # split / merge accounting (pre-dedupe, on parent groups)
    from collections import Counter
    parent_counts = Counter(r["parent_section_id"] for r in recs)
    units_split = sum(1 for c in parent_counts.values() if c > 1)
    subchunks_from_split = sum(c for c in parent_counts.values() if c > 1)
    merged_chunks = len({r["parent_section_id"] for r in recs if r["n_merged"] > 1})
    sections_merged_away = 0
    for pid in {r["parent_section_id"] for r in recs if r["n_merged"] > 1}:
        sections_merged_away += next(r["n_merged"] for r in recs if r["parent_section_id"] == pid) - 1

    recs, empties, thins, dups = dedupe(recs)

    with open(OUT, "w", encoding="utf-8") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    toks_all = [r["token_count"] for r in recs]
    st = _stats(toks_all)
    below = sum(1 for t in toks_all if t < FLOOR)
    over = sum(1 for t in toks_all if t > CAP)

    print("=" * 76, file=out)
    print("PHASE 2 — CHUNKING SUMMARY   ->  %s" % os.path.relpath(OUT, ROOT), file=out)
    print("=" * 76, file=out)
    print("total chunks: %d   (from %d active docs)" % (len(recs), len(active)), file=out)
    print("dropped: %d empty/echo, %d sub-5-word boilerplate, %d exact-body dups"
          % (empties, thins, dups), file=out)
    td = sum(1 for r in recs if r["content_kind"] == "table-degraded")
    print("content_kind=table-degraded (flattened <p>-nested tables): %d" % td, file=out)
    print(file=out)
    print("per-document chunk counts:", file=out)
    for sid in sorted(per_doc):
        kept = sum(1 for r in recs if r["source_id"] == sid)
        ck = "index" if sid in INDEX_SOURCES else ""
        print("   %-30s %3d  %s" % (sid, kept, ck), file=out)
    print(file=out)
    print("token distribution (per chunk): min=%(min)d p25=%(p25)d median=%(median)d "
          "p75=%(p75)d p90=%(p90)d max=%(max)d" % st, file=out)
    print("below floor (<%d): %d   over cap (>%d): %d" % (FLOOR, below, CAP, over), file=out)
    print("cap-split: %d sections -> %d sub-chunks" % (units_split, subchunks_from_split), file=out)
    print("prose merges: %d merged chunks consolidating %d sections"
          % (merged_chunks, sections_merged_away + merged_chunks), file=out)
    print(file=out)
    a = sorted(absorb)
    print("absorption run distribution (canary, ceiling=%d):" % GUARD1_CEILING, file=out)
    print("   qa sections=%d  min=%d median=%d mean=%.2f max=%d  over-ceiling=%d"
          % (len(a), a[0], int(statistics.median(a)), statistics.mean(a), a[-1],
             sum(1 for x in a if x > GUARD1_CEILING)), file=out)
    print("   dist:", dict(sorted(Counter(a).items())), file=out)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--guards", action="store_true")
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()
    if args.guards:
        run_guards()
    if args.write:
        write_and_report()
