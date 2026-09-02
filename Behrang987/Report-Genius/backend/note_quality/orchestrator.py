"""Grade a report's sub-topics against the practice's note-quality rubric.

Three routes to a grade, in this order:

* **Not scored** — the rubric does not cover this sub-topic (none today; the set
  is kept for forward compatibility). These render neutral rather than being guessed at.
* **Red, for free** — the sub-topic holds no notes, so the rubric's RED condition
  ("no meaningful information ... can be identified") is met by inspection. No
  call is made, which is what keeps a mostly-empty report close to free.
* **Judged** — everything else goes to the LLM, one call per report group.

A group call that fails, or a code the judge quietly omits, comes back
``unknown``. That matters: the failure mode of a grader must never be a false
Green.
"""

from __future__ import annotations

import asyncio
import logging

from backend.config import settings
from backend.content_based import review_taxonomy
from backend.note_quality import judge as judge_llm
from backend.note_quality.models import (
    GRADE_RED,
    GRADE_UNKNOWN,
    GradeItem,
    NoteQualityResult,
    SubtopicGrade,
)
from backend.note_quality.prompts import build_judge_messages
from backend.note_quality.rubric import rubric_for

logger = logging.getLogger(__name__)

_EMPTY_REASON = "No notes filed under this sub-topic."


def _prompts_from_messages(messages: list[dict[str, str]]) -> tuple[str, str]:
    system = next(
        (m.get("content") or "" for m in messages if m.get("role") == "system"),
        "",
    )
    user = ""
    for msg in messages:
        if msg.get("role") == "user":
            user = msg.get("content") or ""
    return system, user


def _group_io(
    group_id: str,
    items: list[tuple[str, str]],
    messages: list[dict[str, str]],
    reply: object | None,
) -> dict:
    system_prompt, user_prompt = _prompts_from_messages(messages)
    dump = getattr(reply, "model_dump", lambda: None)() if reply is not None else None
    label = review_taxonomy.GROUP_LABELS.get(group_id, "")
    return {
        "pass": "stage_b_group",
        "group_id": group_id,
        "group_label": label,
        "codes": [code for code, _ in items],
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "input": {
            "items": [{"code": code, "notes": notes} for code, notes in items],
            "messages": messages,
        },
        "model_output": dump,
    }

# The gaps go in a hover tooltip, so a full checklist is unreadable. Four is what
# fits without the surveyor having to scan.
_MAX_MISSING = 4


def _clip(text: str) -> str:
    cap = max(200, int(settings.note_quality_max_chars))
    body = (text or "").strip()
    return body if len(body) <= cap else body[:cap].rstrip() + " …"


def _valid_list(raw: object, allowed: tuple[str, ...]) -> list[str]:
    """Keep only checklist items the rubric actually contains, in rubric order."""
    if not isinstance(raw, (list, tuple)):
        return []
    seen = {str(x).strip().lower() for x in raw if str(x).strip()}
    return [item for item in allowed if item.lower() in seen]


def _by_group(
    pairs: list[tuple[str, str]],
) -> list[tuple[str, list[tuple[str, str]]]]:
    """One batch per report group, in schema order.

    A call never straddles groups, and only the chips in that batch contribute
    a rubric — Inside never sees Outside's criteria.
    """
    buckets: dict[str, list[tuple[str, str]]] = {}
    for code, notes in pairs:
        buckets.setdefault(review_taxonomy.group_for(code), []).append((code, notes))
    for items in buckets.values():
        items.sort(key=lambda pair: review_taxonomy.sort_key(pair[0]))
    order = review_taxonomy.ORDERED_GROUP_IDS
    return sorted(
        buckets.items(),
        key=lambda kv: order.index(kv[0]) if kv[0] in order else len(order),
    )


async def _run_group(
    group_id: str,
    items: list[tuple[str, str]],
    semaphore: asyncio.Semaphore,
) -> tuple[dict[str, SubtopicGrade], dict]:
    label = review_taxonomy.GROUP_LABELS.get(group_id, "")
    messages = build_judge_messages(items, group_label=label)
    async with semaphore:
        reply = await judge_llm.call_judge(messages)
    io = _group_io(group_id, items, messages, reply)
    if reply is None:
        return {}, io

    wanted = {code for code, _ in items}
    out: dict[str, SubtopicGrade] = {}
    for item in reply.judgments:
        code = (item.code or "").strip().lower()
        if code not in wanted or code in out:
            continue
        rubric = rubric_for(code)
        allowed = rubric.relevant if rubric else ()
        present = _valid_list(item.present, allowed)
        # Judges do sometimes list the same item as both covered and missing.
        # present wins, so the tooltip cannot read "found X / missing X".
        missing = [item_ for item_ in _valid_list(item.missing, allowed) if item_ not in present]
        out[code] = SubtopicGrade(
            code=code,
            grade=item.grade,
            present=present,
            missing=missing[:_MAX_MISSING],
            reason=(item.reason or "").strip(),
            method="judge",
        )
    return out, io


async def grade_subtopics(items: list[GradeItem]) -> NoteQualityResult:
    """Grade each sub-topic's notes Green / Yellow / Red against its rubric."""
    result = NoteQualityResult()

    to_judge: list[tuple[str, str]] = []
    seen: set[str] = set()
    for item in items:
        code = (item.code or "").strip().lower()
        if not code or code in seen:
            continue
        seen.add(code)

        if rubric_for(code) is None:
            result.not_scored.append(code)
            continue

        notes = (item.notes or "").strip()
        if not notes:
            result.grades[code] = SubtopicGrade(
                code=code,
                grade=GRADE_RED,
                reason=_EMPTY_REASON,
                method="empty",
            )
            continue
        to_judge.append((code, _clip(notes)))

    if not to_judge:
        result.llm_available = judge_llm.is_available()
        result.unavailable_reason = judge_llm.unavailable_reason()
        return result

    groups = _by_group(to_judge)
    result.call_count = len(groups)

    if not judge_llm.is_available():
        result.unavailable_reason = judge_llm.unavailable_reason()
        for code, _notes in to_judge:
            result.grades[code] = SubtopicGrade(
                code=code, grade=GRADE_UNKNOWN, method="unavailable"
            )
        result.llm_io = [
            _group_io(
                gid,
                batch,
                build_judge_messages(
                    batch, group_label=review_taxonomy.GROUP_LABELS.get(gid, "")
                ),
                None,
            )
            for gid, batch in groups
        ]
        return result

    result.llm_available = True

    semaphore = asyncio.Semaphore(max(1, int(settings.note_quality_concurrency)))
    graded_groups = await asyncio.gather(
        *(_run_group(gid, batch, semaphore) for gid, batch in groups)
    )

    graded: dict[str, SubtopicGrade] = {}
    io_log: list[dict] = []
    for group_result, io in graded_groups:
        graded.update(group_result)
        io_log.append(io)
    result.llm_io = io_log

    for code, _notes in to_judge:
        # A code the judge skipped stays unknown rather than inheriting a grade.
        result.grades[code] = graded.get(
            code, SubtopicGrade(code=code, grade=GRADE_UNKNOWN, method="error")
        )
    result.judged_count = sum(
        1 for g in result.grades.values() if g.method == "judge"
    )
    return result
