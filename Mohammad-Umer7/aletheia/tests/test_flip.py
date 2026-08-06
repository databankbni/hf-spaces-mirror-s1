"""THE flip test: Aletheia visibly changes its mind when a source is retracted.

Full programmatic run of the demo narrative (spec sections 6 and 9):
  reset -> seed helios + meridian + northfield -> ask -> helios must be scoped+cited
  -> ingest the retraction notice -> retract helios (and meridian, which only
  repeats the claim) -> changelog records real node deaths -> ask again ->
  retracted datasets are out of scope, the answer changed, and the discredited
  "40%" figure is gone.

LLM output varies run to run, so structural assertions (scoping, citations,
changelog, node removal) carry the test; wording assertions are limited to the
one the demo depends on (the discredited figure disappearing).

Runtime: several minutes (real Groq calls, sequential ingestion). Run twice:
    pytest tests/test_flip.py; pytest tests/test_flip.py
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import changelog, sources
from backend.seed_data import DEMO_QUESTION, SEED_SOURCES

RETRACTION_REASON = "Journal retraction: fabricated data"


def _seed_spec(source_id: str) -> dict:
    return next(s for s in SEED_SOURCES if s["id"] == source_id)


async def _flip() -> None:
    # --- stage 1: a world where the claim is credible ---
    await sources.seed_demo(include_retraction=False)
    registry = {s["id"]: s for s in sources.list_sources()}
    assert set(registry) == {"helios_study", "meridian_post", "northfield_meta"}
    for s in registry.values():
        assert s["trust"] == "trusted" and s["status"] == "ready"
        assert len(s["node_ids"]) > 0, f"{s['id']} has no attributed nodes"

    ask1 = await sources.ask(DEMO_QUESTION)
    answer1 = ask1["answer"]
    print(f"\nanswer1: {answer1}\ncited1: {[c['id'] for c in ask1['cited_sources']]}")
    assert answer1, "ask() returned no answer with three trusted sources"
    assert "src_helios_study" in ask1["scoped_datasets"], "helios must be in recall scope"
    assert "helios_study" in {c["id"] for c in ask1["cited_sources"]}, (
        "helios must be cited before the retraction"
    )
    assert ask1["highlight_node_ids"], "cited sources must contribute highlight nodes"

    # --- stage 2: the retraction notice arrives — and Aletheia NOTICES ---
    spec = _seed_spec("jch_retraction")
    ingested = await sources.ingest_source(
        spec["title"], spec["kind"], spec["text"], source_id=spec["id"]
    )
    conflicts = ingested["conflicts"]
    print(f"\nconflicts: {conflicts}")
    assert conflicts, "Aletheia must detect that the retraction disputes a trusted source"
    disputed_ids = {c["disputed_source_id"] for c in conflicts}
    assert "helios_study" in disputed_ids, f"helios must be disputed, got {disputed_ids}"
    helios_conflict = next(c for c in conflicts if c["disputed_source_id"] == "helios_study")
    assert helios_conflict["reason"].strip(), "the conflict must carry a human-readable reason"

    # --- stage 3: Aletheia changes its mind ---
    # Same code path as the conflict card's Retract button: the API endpoint calls
    # retract_source(reenrich=False) and schedules reenrich_remaining() afterwards.
    result = await sources.retract_source(
        "helios_study", helios_conflict["reason"], reenrich=False
    )
    assert result["nodes_removed"] > 0, "retracting helios must actually remove graph nodes"
    assert result["removed_node_ids"], "the frontend needs the dying node ids"
    assert result["links_removed"] > 0, "severed links drive the retraction ticker"

    retractions = [e for e in changelog.read_entries() if e["type"] == "retraction"]
    assert len(retractions) == 1, f"expected 1 retraction changelog entry, got {len(retractions)}"
    assert retractions[0]["nodes_removed"] == result["nodes_removed"] > 0
    assert retractions[0]["source_id"] == "helios_study"

    # The news piece only repeats the retracted claim (spec section 9's optional step).
    result2 = await sources.retract_source("meridian_post", RETRACTION_REASON, reenrich=False)
    assert result2["nodes_removed"] > 0

    await sources.reenrich_remaining()  # the API runs this in the background after retracts

    retractions = [e for e in changelog.read_entries() if e["type"] == "retraction"]
    assert len(retractions) == 2

    # --- stage 4: the corrected worldview ---
    ask2 = await sources.ask(DEMO_QUESTION)
    answer2 = ask2["answer"]
    print(f"\nanswer2: {answer2}\ncited2: {[c['id'] for c in ask2['cited_sources']]}")
    assert answer2, "ask() must still answer from the remaining trusted sources"

    # (a) retracted knowledge is structurally unreachable
    assert "src_helios_study" not in ask2["scoped_datasets"]
    assert "src_meridian_post" not in ask2["scoped_datasets"]
    assert {c["id"] for c in ask2["cited_sources"]}.isdisjoint({"helios_study", "meridian_post"})

    # (b) the answer actually changed
    assert answer2.strip() != answer1.strip(), "answer must change after the retraction"

    # (c) the discredited figure is gone
    assert "40%" not in answer2, f"answer2 still repeats the discredited figure: {answer2!r}"

    # and what actually works is now the story
    assert "northfield_meta" in {c["id"] for c in ask2["cited_sources"]}, (
        "the corrected answer should cite the meta-analysis"
    )


def test_flip():
    asyncio.run(_flip())
