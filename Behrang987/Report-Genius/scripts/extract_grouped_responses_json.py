"""Extract Andromeda grouped-responses PDF into structured SP JSON."""

from __future__ import annotations

import json
import re
from pathlib import Path

from pypdf import PdfReader

PDF_DEFAULT = Path(r"E:\my report ai\Grouped_Responses_Restructured_DEDUPED_v2.pdf")
OUT_DEFAULT = Path(
    r"E:\my report ai\Report-genius-ai\backend\standard_paragraphs\samples"
    r"\grouped_responses_full.json"
)

PARENT_RE = re.compile(
    r"^(?P<code>[A-J])\s*[\u2014\u2013\-]\s*(?P<title>.+)$",
    re.M,
)
CANON_LEAVES = {f"{letter}{n}" for letter in "ABCDEFGHIJ" for n in range(1, 20)}

_SENTENCE_START = re.compile(
    r"^(The|We|There|From|This|It|However|Once|If|As|In|These|Their|Any|Also|"
    r"When|Whilst|While|Although|Our|You|I |A |An |Over |Where |Defective |"
    r"Because |Since |After |Before |During |With |Without |To |For |And |"
    r"But |Or |Not |No |Yes )\b",
    re.I,
)


def _parent_for(parents: list[dict], pos: int) -> dict | None:
    cur = None
    for p in parents:
        if p["pos"] <= pos:
            cur = p
        else:
            break
    return cur


def parse_responses(raw: str) -> list[dict]:
    lines = raw.splitlines()
    responses: list[dict] = []
    cur_label: str | None = None
    cur_buf: list[str] = []
    preamble = True

    def flush() -> None:
        nonlocal cur_label, cur_buf
        text = " ".join(x.strip() for x in cur_buf if x.strip())
        text = re.sub(r"\s+", " ", text).strip()
        cur_buf = []
        if not text or "no predefined responses" in text.lower():
            cur_label = None
            return
        min_len = 15 if cur_label is not None else 40
        if len(text) < min_len:
            cur_label = None
            return
        responses.append({"label": cur_label or "", "text": text})
        cur_label = None

    for ln in lines:
        s = ln.strip()
        if not s:
            continue
        is_label = (
            s.endswith(":")
            and 2 <= len(s) <= 120
            and not s.startswith("||")
            and "Condition Rating" not in s
            and not _SENTENCE_START.match(s)
        )
        if is_label and s[0].islower() and not s.lower().startswith(
            ("unfelt", "possibly")
        ):
            is_label = False
        if is_label:
            if preamble and cur_buf:
                cur_label = None
                flush()
            elif not preamble:
                flush()
            preamble = False
            cur_label = s[:-1].strip()
            cur_buf = []
        else:
            cur_buf.append(s)
    flush()
    return responses


def extract(pdf_path: Path) -> dict:
    reader = PdfReader(str(pdf_path))
    full = "\n".join((p.extract_text() or "") for p in reader.pages)

    parents_raw = []
    for m in PARENT_RE.finditer(full):
        parents_raw.append(
            {
                "pos": m.start(),
                "code": m.group("code"),
                "title": m.group("title").strip().split("\n")[0][:120],
            }
        )
    seen_p: dict[str, dict] = {}
    for p in parents_raw:
        seen_p.setdefault(p["code"], p)
    parents = [seen_p[c] for c in sorted(seen_p)]

    lines = full.splitlines()
    offsets: list[int] = []
    o = 0
    for ln in lines:
        offsets.append(o)
        o += len(ln) + 1

    field_blocks: list[dict] = []
    for i, ln in enumerate(lines):
        m = re.match(r"^Field ref:\s*(\d+)\s*$", ln.strip())
        if not m:
            continue
        ref = m.group(1)
        title = ""
        for j in range(i - 1, max(-1, i - 6), -1):
            t = lines[j].strip()
            if not t:
                continue
            if re.match(r"^[A-J]\s*[\u2014\u2013\-]", t):
                break
            title = t
            break
        leaf = None
        leaf_title = title
        mleaf = re.match(r"^([A-J]\d{1,2})\s+(.+)$", title)
        if mleaf and mleaf.group(1) in CANON_LEAVES:
            leaf = mleaf.group(1)
            leaf_title = mleaf.group(2).strip()
        field_blocks.append(
            {
                "pos": offsets[i],
                "field_ref": ref,
                "raw_title": title,
                "subsection_id": leaf,
                "subsection_name": leaf_title if leaf else title,
            }
        )

    for i, fb in enumerate(field_blocks):
        end = field_blocks[i + 1]["pos"] if i + 1 < len(field_blocks) else len(full)
        raw = full[fb["pos"] : end]
        fb["raw"] = re.sub(r"^Field ref:\s*\d+\s*\n?", "", raw, count=1)

    by_parent = {
        p["code"]: {
            "section_id": p["code"],
            "section_name": p["title"],
            "subsections": [],
        }
        for p in parents
    }

    empty_fields = 0
    total_sps = 0
    for fb in field_blocks:
        par = _parent_for(parents, fb["pos"])
        if not par:
            continue
        resps = parse_responses(fb["raw"])
        if not resps:
            if "no predefined responses" in fb["raw"].lower():
                empty_fields += 1
            else:
                body = re.sub(r"\s+", " ", fb["raw"]).strip()
                if (
                    body
                    and "no predefined responses" not in body.lower()
                    and len(body) >= 15
                ):
                    resps = [{"label": "", "text": body}]
        sid = fb["subsection_id"] or f"field_{fb['field_ref']}"
        sname = fb["subsection_name"] or fb["raw_title"] or sid
        total_sps += len(resps)
        by_parent[par["code"]]["subsections"].append(
            {
                "section_id": par["code"],
                "subsection_id": sid,
                "subsection_name": sname,
                "field_ref": fb["field_ref"],
                "has_rics_code": bool(fb["subsection_id"]),
                "standard_paragraphs": [
                    {"label": r["label"], "text": r["text"]} for r in resps
                ],
            }
        )

    return {
        "source": pdf_path.name,
        "page_count": len(reader.pages),
        "stats": {
            "sections": len(by_parent),
            "fields": len(field_blocks),
            "empty_fields": empty_fields,
            "standard_paragraphs": total_sps,
        },
        "sections": [by_parent[c] for c in sorted(by_parent.keys())],
    }


def main() -> None:
    payload = extract(PDF_DEFAULT)
    OUT_DEFAULT.parent.mkdir(parents=True, exist_ok=True)
    OUT_DEFAULT.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    print("wrote", OUT_DEFAULT)
    print("size_mb", round(OUT_DEFAULT.stat().st_size / 1e6, 2))
    print("stats", payload["stats"])
    for sec in payload["sections"]:
        nsp = sum(len(s["standard_paragraphs"]) for s in sec["subsections"])
        print(
            f"  {sec['section_id']}: {len(sec['subsections'])} fields, {nsp} SPs"
        )


if __name__ == "__main__":
    main()
