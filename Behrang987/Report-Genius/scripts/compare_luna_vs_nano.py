"""Fair Luna vs nano comparison (merge isolated, then generators isolated).

Phase A — freeze past+SP drafts from prompt-compare-20260808-063123,
           re-merge with gpt-5.4-nano and gpt-5.6-luna at the same merge temp.
Phase B — regenerate past+SP only (no merge), swapping MAPPING_MODEL only.

Usage:
  python scripts/compare_luna_vs_nano.py
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Force models via env BEFORE settings import for generator phase; merge phase
# sets env and reloads settings per model via os.environ + settings rebuild.

FROZEN = (
    _ROOT
    / "docs"
    / "dual-path-merge-runs"
    / "prompt-compare-20260808-063123"
)
MODELS = ("gpt-5.4-nano", "gpt-5.6-luna")
MERGE_TEMP = 0.2
PROMPT_VERSION = "v2"
TENANT = "khanchaudhry3@gmail.com"

SECTIONS: dict[str, dict[str, str]] = {
    "D1": {
        "title": "Chimney stacks",
        "notes": (
            "The chimney stack is of brick, with chimney pots. Clay pots show "
            "signs of cracking and spalling. TV aerial attach was okay. "
            "Chimney was reasonably aligned."
        ),
    },
    "D2": {
        "title": "Roof coverings",
        "notes": (
            "The roof is a pitched with interlocking concrete tiles. The roof "
            "has been replaced. The date of this replacement could not be "
            "confirmed. Parapet walls have been rendered and the render showed "
            "cracks. Distening was observed to the parapet walls below coping "
            "stones. Flashings at the abutments of parapet walls and roof are "
            "lead. Some sections have been lifted, creating gaps. The mortar "
            "bed into the ridge tiles is deteriorated. There is some moss and "
            "lichen growth. The main roof covering is serviceable order and "
            "no deflection."
        ),
    },
    "D4": {
        "title": "Main walls",
        "notes": (
            "The main walls are of solid construction, approximately 285 mm "
            "thick. The damp-proof course is concealed. External ground levels "
            "appear to be at an adequate height in relation to the internal "
            "floor level.\n\n"
            "The rendered wall surfaces show evidence of cracking. The window "
            "sills and surrounds have been rendered and painted, and cracking "
            "was also noted in these areas. The gaps where the doors and "
            "windows abut the main walls have been sealed with mortar fillets, "
            "which also exhibit cracking.\n\n"
            "A movement-related crack was noted to the front bay. The cracks "
            "measured less than 5 mm in width. However, future movement cannot "
            "be ruled out. Please give the 4 options regarding the "
            "implications of the observed structural movement."
        ),
    },
}

_HALLU = {
    "D1": ["spreading", "frost", "water penetration and frost"],
    "D2": [],
    "D4": [],
}
_STYLE = {
    "D1": ["condition rating", "reasonably aligned", "tv aerial"],
    "D2": ["scaffolding", "interlocking concrete", "disten"],
    "D4": ["option 1", "option 2", "option 3", "option 4"],
}


def _clean(text: str) -> str:
    t = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    while "\n\n\n" in t:
        t = t.replace("\n\n\n", "\n\n")
    return t.strip() + ("\n" if t.strip() else "")


def _model_tag(model: str) -> str:
    return model.replace(".", "").replace("-", "")


def _first_diff(a: str, b: str) -> str:
    if a == b:
        return "identical"
    n = min(len(a), len(b))
    i = 0
    while i < n and a[i] == b[i]:
        i += 1
    sn1 = a[max(0, i - 40) : i + 80].replace("\n", " ")
    sn2 = b[max(0, i - 40) : i + 80].replace("\n", " ")
    return f"@{i}: nano…{sn1}… | luna…{sn2}…"


def phase_merge(out_dir: Path) -> dict:
    from backend.merge_agent import DualPathDraft, merge_dual_path_drafts

    merge_dir = out_dir / "phase_a_merge_only"
    merge_dir.mkdir(parents=True, exist_ok=True)
    meta: dict = {
        "phase": "merge_only",
        "frozen_from": str(FROZEN.relative_to(_ROOT)),
        "merge_temperature": MERGE_TEMP,
        "prompt_version": PROMPT_VERSION,
        "models": list(MODELS),
        "sections": {},
    }
    analysis = [
        "# Phase A — merge only (frozen nano drafts)",
        "",
        f"Frozen inputs: `{FROZEN.name}`",
        f"Merge temp={MERGE_TEMP}, prompt={PROMPT_VERSION}, models={list(MODELS)}",
        "",
    ]

    for sid in ("D1", "D2", "D4"):
        past = (FROZEN / sid.lower() / "past_report_draft.txt").read_text(
            encoding="utf-8"
        )
        sp = (FROZEN / sid.lower() / "standard_paragraph_draft.txt").read_text(
            encoding="utf-8"
        )
        notes = (FROZEN / sid.lower() / "inspection_notes.txt").read_text(
            encoding="utf-8"
        )
        title = SECTIONS[sid]["title"]
        sec_dir = merge_dir / sid.lower()
        sec_dir.mkdir(parents=True, exist_ok=True)
        (sec_dir / "past_report_draft.txt").write_text(_clean(past), encoding="utf-8")
        (sec_dir / "standard_paragraph_draft.txt").write_text(
            _clean(sp), encoding="utf-8"
        )
        (sec_dir / "inspection_notes.txt").write_text(_clean(notes), encoding="utf-8")

        merges: dict[str, str] = {}
        print(f"\n=== Phase A merge {sid} ===")
        for model in MODELS:
            draft = DualPathDraft(
                section_id=sid,
                section_title=title,
                past_report_draft=past,
                standard_paragraph_draft=sp,
                past_report_source="frozen-063123-past",
                standard_paragraph_source="frozen-063123-sp",
                inspection_notes=notes,
            )
            result = merge_dual_path_drafts(
                draft,
                temperature=MERGE_TEMP,
                prompt_version=PROMPT_VERSION,
                model=model,
            )
            tag = _model_tag(model)
            text = _clean(result.merged_text)
            (sec_dir / f"merged_{tag}.txt").write_text(text, encoding="utf-8")
            merges[model] = text
            print(
                f"  {model}: status={result.meta.get('status')} "
                f"chars={len(text.strip())} model={result.model}"
            )

        nano = merges[MODELS[0]].strip()
        luna = merges[MODELS[1]].strip()
        low_n, low_l = nano.lower(), luna.lower()
        analysis.append(f"## {sid}")
        analysis.append("")
        analysis.append(f"- nano chars: {len(nano)} (past={len(past.strip())})")
        analysis.append(f"- luna chars: {len(luna)}")
        analysis.append(
            f"- nano style markers: {[m for m in _STYLE[sid] if m in low_n] or 'none'}"
        )
        analysis.append(
            f"- luna style markers: {[m for m in _STYLE[sid] if m in low_l] or 'none'}"
        )
        if _HALLU[sid]:
            analysis.append(
                f"- nano hallu: {[m for m in _HALLU[sid] if m in low_n] or 'none'}"
            )
            analysis.append(
                f"- luna hallu: {[m for m in _HALLU[sid] if m in low_l] or 'none'}"
            )
        analysis.append(f"- diff: {_first_diff(nano, luna)}")
        analysis.append("")
        meta["sections"][sid] = {
            "past_chars": len(past.strip()),
            "sp_chars": len(sp.strip()),
            "merged_chars": {m: len(merges[m].strip()) for m in MODELS},
            "identical": nano == luna,
        }

    (merge_dir / "ANALYSIS.md").write_text("\n".join(analysis) + "\n", encoding="utf-8")
    (merge_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return meta


async def _generate_past(
    *,
    sid: str,
    notes: str,
    schema,
    id_to_unit,
    property_context,
    policy,
    draft_id: str,
) -> dict:
    from backend.models.section import SectionNote
    from backend.pipeline import section_mapper
    from backend.rag.types import KNOWLEDGE_SOURCE_PAST_REPORT
    from backend.storage import retrieval_manifest
    from backend.merge_agent import source_names_from_manifest_section

    note = SectionNote(
        section_id=sid, raw_observations=[notes.strip()], text=notes.strip()
    )
    section, unmatched = await section_mapper._process_one_section(
        sid,
        schema=schema,
        tenant_id=TENANT,
        by_id={sid: note},
        id_to_unit=id_to_unit,
        report_draft_id=f"{draft_id}-past",
        interference_level=policy.interference_level,
        retrieval_level="paragraph",
        allowed_doc_keys=None,
        property_context=property_context,
        policy=policy,
        knowledge_source=KNOWLEDGE_SOURCE_PAST_REPORT,
    )
    manifest = str(
        retrieval_manifest.retrieval_manifest_path(TENANT, f"{draft_id}-past")
    )
    return {
        "status": str(section.status),
        "generated_text": _clean(section.text or ""),
        "unmatched": list(unmatched or []),
        "manifest": manifest,
        "sources": source_names_from_manifest_section(manifest, sid),
    }


def _generate_sp(*, sid: str, title: str, notes: str, schema, draft_id: str) -> dict:
    from backend.merge_agent import source_names_from_chunks
    from backend.rag.types import KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH
    from backend.standard_paragraphs.generate import generate_from_standard_paragraphs
    from backend.storage import retrieval_manifest

    text, hits, messages, guidance, issues, llm_usage, style_sample_count = (
        generate_from_standard_paragraphs(
            tenant_id=TENANT,
            schema=schema,
            section_id=sid,
            section_title=title,
            observations=[notes.strip()],
            candidate_ids=[sid],
            force_decompose=True,
            force_decompose_llm=True,
            use_all_section_sps=False,
            style_samples_enabled=False,
        )
    )
    retrieval_manifest.record_section_retrieval(
        TENANT,
        f"{draft_id}-sp",
        section_id=sid,
        section_title=title,
        observations=[notes.strip()],
        baseline_text=guidance or "",
        hits=hits,
        status="MAPPED" if (text or "").strip() else "NO_RAG_MATCH",
        prompt_messages=messages,
        retrieved_count=len(hits),
        prompt_chunk_count=len(hits),
        knowledge_source=KNOWLEDGE_SOURCE_STANDARD_PARAGRAPH,
        generated_text=text or "",
        retrieval_issues=list(issues or []),
        llm_usage=llm_usage,
        style_sample_count=style_sample_count,
    )
    sources = source_names_from_chunks(
        [
            {
                "source_filename": getattr(h, "source_filename", "") or "",
                "doc_id": getattr(h, "doc_id", "") or "",
                "paragraph_index": getattr(h, "paragraph_index", None),
            }
            for h in (hits or [])
        ],
        unique=False,
        include_paragraph_index=True,
    )
    return {
        "status": "MAPPED" if (text or "").strip() else "NO_RAG_MATCH",
        "generated_text": _clean(text or ""),
        "hit_count": len(hits or []),
        "findings": list(issues or []),
        "llm_usage": llm_usage,
        "sources": sources,
        "manifest": str(
            retrieval_manifest.retrieval_manifest_path(TENANT, f"{draft_id}-sp")
        ),
    }


async def _phase_generate_one_model(out_dir: Path, model: str) -> dict:
    """Generate past+SP for one model in this process (fresh settings via env)."""
    from backend import config
    from backend.domain import template_discoverer
    from backend.domain.interference import GenerationPolicy
    from backend.domain.notes.survey_notes import build_property_context, parse_notes
    from backend.domain.rics_level3_schema import (
        mapping_units_for_parent,
        ordered_parent_sections,
    )
    from backend.merge_agent import write_sources_file

    # Ensure this process sees the intended mapping model.
    config.get_settings.cache_clear()
    config.settings = config.get_settings()
    S = config.settings
    if S.mapping_model != model:
        raise RuntimeError(
            f"MAPPING_MODEL mismatch: env wanted {model!r}, settings={S.mapping_model!r}"
        )

    gen_dir = out_dir / "phase_b_generate_only"
    tag = _model_tag(model)
    model_dir = gen_dir / tag
    model_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    draft_id = f"model-compare-{tag}-{stamp}"

    schema = template_discoverer.ensure_canonical_schema(TENANT)
    id_to_unit = {
        sec.id: sec
        for parent in ordered_parent_sections(schema)
        for sec in mapping_units_for_parent(schema, parent.id)
    }
    property_context = build_property_context(
        parse_notes(SECTIONS["D1"]["notes"]),
        property_type="house",
        tenure="freehold",
    )
    policy = GenerationPolicy.resolve("assist", 3)

    print(f"\n=== Phase B generate model={model} temp={S.mapping_temperature} ===")
    model_meta: dict = {
        "mapping_model": S.mapping_model,
        "mapping_temperature": S.mapping_temperature,
        "mapping_reasoning_effort": S.mapping_reasoning_effort,
        "standard_paragraphs_temperature": S.standard_paragraphs_temperature,
        "draft_id": draft_id,
        "sections": {},
    }

    for sid in ("D1", "D2", "D4"):
        title = SECTIONS[sid]["title"]
        notes = SECTIONS[sid]["notes"]
        print(f"  --- {sid} past ---")
        past = await _generate_past(
            sid=sid,
            notes=notes,
            schema=schema,
            id_to_unit=id_to_unit,
            property_context=property_context,
            policy=policy,
            draft_id=draft_id,
        )
        print(f"  --- {sid} sp ---")
        sp = await asyncio.to_thread(
            _generate_sp,
            sid=sid,
            title=title,
            notes=notes,
            schema=schema,
            draft_id=draft_id,
        )
        sec_dir = model_dir / sid.lower()
        sec_dir.mkdir(parents=True, exist_ok=True)
        (sec_dir / "inspection_notes.txt").write_text(_clean(notes), encoding="utf-8")
        (sec_dir / "past_report_draft.txt").write_text(
            past["generated_text"], encoding="utf-8"
        )
        (sec_dir / "standard_paragraph_draft.txt").write_text(
            sp["generated_text"], encoding="utf-8"
        )
        write_sources_file(
            sec_dir / "past_report_sources.txt",
            past.get("sources") or [],
            header="Past-report retrieval sources",
        )
        write_sources_file(
            sec_dir / "standard_paragraph_sources.txt",
            sp.get("sources") or [],
            header="Standard-paragraph retrieval sources",
        )
        (sec_dir / "readable.txt").write_text(
            (
                f"SECTION {sid} — {title}\nmodel={model}\n\n"
                f"===== PAST ({past['status']}) =====\n\n{past['generated_text']}\n"
                f"===== SP ({sp['status']}) =====\n\n{sp['generated_text']}"
            ),
            encoding="utf-8",
        )
        print(
            f"  {sid}: past={past['status']} chars={len(past['generated_text'].strip())} "
            f"sp={sp['status']} chars={len(sp['generated_text'].strip())}"
        )
        model_meta["sections"][sid] = {
            "past_status": past["status"],
            "past_chars": len(past["generated_text"].strip()),
            "past_manifest": past.get("manifest"),
            "sp_status": sp["status"],
            "sp_chars": len(sp["generated_text"].strip()),
            "sp_hit_count": sp.get("hit_count"),
            "sp_findings": sp.get("findings"),
            "sp_manifest": sp.get("manifest"),
        }
    (model_dir / "meta.json").write_text(
        json.dumps(model_meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return model_meta


def phase_generate(out_dir: Path) -> dict:
    """Run each generator model in a fresh subprocess (avoids cached Settings)."""
    import subprocess

    gen_dir = out_dir / "phase_b_generate_only"
    gen_dir.mkdir(parents=True, exist_ok=True)
    meta: dict = {
        "phase": "generate_only",
        "models": list(MODELS),
        "sections": {},
    }
    analysis = [
        "# Phase B — generate only (past + SP, swap MAPPING_MODEL)",
        "",
        "Same house notes + property_type=house; no merge.",
        "Each model runs in a fresh Python process.",
        f"Models: {list(MODELS)}",
        "",
    ]

    for model in MODELS:
        env = os.environ.copy()
        env["MAPPING_MODEL"] = model
        env["MAPPING_REASONING_EFFORT"] = "none"
        env["STANDARD_PARAGRAPHS_REASONING_EFFORT"] = "none"
        # Do not inherit a stale merge override as mapping fallback noise.
        env.pop("MERGE_AGENT_MODEL", None)
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--phase-b-model",
            model,
            "--out-dir",
            str(out_dir),
        ]
        print(f"\n>>> subprocess generate {model}")
        proc = subprocess.run(cmd, cwd=str(_ROOT), env=env, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"phase B failed for {model} exit={proc.returncode}")
        tag = _model_tag(model)
        model_meta = json.loads((gen_dir / tag / "meta.json").read_text(encoding="utf-8"))
        meta["sections"][tag] = model_meta

    for sid in ("D1", "D2", "D4"):
        nano_past = (
            gen_dir / _model_tag(MODELS[0]) / sid.lower() / "past_report_draft.txt"
        ).read_text(encoding="utf-8").strip()
        luna_past = (
            gen_dir / _model_tag(MODELS[1]) / sid.lower() / "past_report_draft.txt"
        ).read_text(encoding="utf-8").strip()
        nano_sp = (
            gen_dir
            / _model_tag(MODELS[0])
            / sid.lower()
            / "standard_paragraph_draft.txt"
        ).read_text(encoding="utf-8").strip()
        luna_sp = (
            gen_dir
            / _model_tag(MODELS[1])
            / sid.lower()
            / "standard_paragraph_draft.txt"
        ).read_text(encoding="utf-8").strip()
        analysis.append(f"## {sid}")
        analysis.append("")
        analysis.append(f"- past nano/luna chars: {len(nano_past)} / {len(luna_past)}")
        analysis.append(f"- sp nano/luna chars: {len(nano_sp)} / {len(luna_sp)}")
        analysis.append(
            f"- past style nano: {[m for m in _STYLE[sid] if m in nano_past.lower()] or 'none'}"
        )
        analysis.append(
            f"- past style luna: {[m for m in _STYLE[sid] if m in luna_past.lower()] or 'none'}"
        )
        if _HALLU[sid]:
            analysis.append(
                f"- sp hallu nano: {[m for m in _HALLU[sid] if m in nano_sp.lower()] or 'none'}"
            )
            analysis.append(
                f"- sp hallu luna: {[m for m in _HALLU[sid] if m in luna_sp.lower()] or 'none'}"
            )
        analysis.append(f"- past diff: {_first_diff(nano_past, luna_past)}")
        analysis.append(f"- sp diff: {_first_diff(nano_sp, luna_sp)}")
        analysis.append("")

    (gen_dir / "ANALYSIS.md").write_text("\n".join(analysis) + "\n", encoding="utf-8")
    (gen_dir / "meta.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return meta


def _write_verdict(out_dir: Path) -> None:
    a = (out_dir / "phase_a_merge_only" / "ANALYSIS.md").read_text(encoding="utf-8")
    b = (out_dir / "phase_b_generate_only" / "ANALYSIS.md").read_text(encoding="utf-8")
    body = [
        "# Luna vs nano — fair compare",
        "",
        f"Run: `{out_dir.name}`",
        "",
        "1. **Phase A** freezes nano past+SP from `prompt-compare-20260808-063123` "
        "and re-merges with each model at the same merge temp (isolates merger).",
        "2. **Phase B** regenerates past+SP only with each `MAPPING_MODEL` "
        "(isolates generators).",
        "",
        "Inspect section folders for full prose; use ANALYSIS sections below for diffs.",
        "",
        a,
        "",
        b,
        "",
    ]
    (out_dir / "VERDICT.md").write_text("\n".join(body), encoding="utf-8")


async def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] == "--phase-b-model":
        # Subprocess entry: python script.py --phase-b-model MODEL --out-dir DIR
        model = args[1]
        out_dir = Path(args[args.index("--out-dir") + 1])
        await _phase_generate_one_model(out_dir, model)
        return 0

    if not FROZEN.is_dir():
        print("missing frozen pack", FROZEN)
        return 1
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    out_dir = _ROOT / "docs" / "dual-path-merge-runs" / f"luna-vs-nano-{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    print("out_dir=", out_dir)

    phase_merge(out_dir)
    phase_generate(out_dir)
    _write_verdict(out_dir)

    (out_dir / "meta.json").write_text(
        json.dumps(
            {
                "run_id": out_dir.name,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "frozen_from": str(FROZEN.relative_to(_ROOT)),
                "models": list(MODELS),
                "merge_temperature": MERGE_TEMP,
                "prompt_version": PROMPT_VERSION,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print("Wrote", out_dir / "VERDICT.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
